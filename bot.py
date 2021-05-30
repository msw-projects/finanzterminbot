import os
import praw
import re
import requests
import random
import sqlite3
import json
import time
import traceback
from lxml import html
from logger import log

DATABASE_PATH = os.path.join(os.path.dirname(__file__), "bot.db")

class CompanyEventsBot(object):
    def __init__(self, client_id, client_secret, username, password, *, args):
        log.debug("Initializing Bot...")
        self.args = args
        # init PRAW credentials
        self.reddit = praw.Reddit(
            user_agent="MSW Finanzterminbot (by u/sharkmageddon)",
            client_id=client_id,
            client_secret=client_secret,
            username=username,
            password=password,
        )
        # init database
        self._init_db()
        self._clean_db()
        # init requests session
        self.session = requests.Session()
        self.user_agent_list = [
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.1.1 Safari/605.1.15',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:77.0) Gecko/20100101 Firefox/77.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.97 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:77.0) Gecko/20100101 Firefox/77.0',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.97 Safari/537.36',
        ]
        self.session.headers.update({
            'Accept': 'text/html, text/plain, */*',
            'User-Agent': random.choice(self.user_agent_list),
            'Accept-Language': 'de-de',
            'Referer': 'https://www.finanzen.net/',
        })
        log.debug("Bot ready")

    def _init_db(self):
        """Initializes database connection and creates necessary tables if they don't exist."""
        self.con = sqlite3.connect(DATABASE_PATH)
        self.con.row_factory = sqlite3.Row
        cur = self.con.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS responded_to (comment_id TEXT PRIMARY KEY, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        cur.execute("CREATE TABLE IF NOT EXISTS company (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, isin TEXT UNIQUE, wkn TEXT, symbol TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS event (id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER, date TEXT, type TEXT, info TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        self.con.commit()
    
    def _clean_db(self):
        """Removes old values from the database."""
        cur = self.con.cursor()
        cur.execute("DELETE FROM responded_to WHERE created_at <= date('now','-7 day')")
        cur.execute("DELETE FROM event WHERE created_at <= date('now','-7 day')")
        self.con.commit()

    def register_response(self, comment_id):
        """Registers response in database."""
        cur = self.con.cursor()
        cur.execute("INSERT INTO responded_to (comment_id) VALUES (?)", (comment_id,))
        self.con.commit()
    
    def already_responded(self, comment_id):
        """Checks if we have already responded to this comment."""
        cur = self.con.cursor()
        cur.execute("SELECT comment_id FROM responded_to WHERE comment_id = ?", (comment_id,))
        return cur.fetchone() is not None
    
    def insert_company(self, name, isin, wkn, symbol):
        """Inserts company into database."""
        cur = self.con.cursor()
        cur.execute("INSERT OR REPLACE INTO company (name, isin, wkn, symbol) VALUES (?, ?, ?, ?)", (name, isin, wkn, symbol))
        self.con.commit()
        return cur.lastrowid

    def get_company(self, search_term):
        """Finds company in database from search term (must match exactly)."""
        cur = self.con.cursor()
        cur.execute("SELECT * FROM company WHERE wkn = :q OR isin = :q OR symbol = :q", {'q': search_term})
        found = cur.fetchone()
        return dict(found) if found else None

    def insert_event(self, company_id, event_date, event_type, event_info):
        """Stores company data in cache."""
        cur = self.con.cursor()
        cur.execute("INSERT INTO event (company_id, date, type, info) VALUES (?, ?, ?, ?)", (company_id, event_date, event_type, event_info))
        self.con.commit()

    def get_events(self, company_id):
        """Returns cached company data for ISIN."""
        cur = self.con.cursor()
        cur.execute("SELECT * FROM event WHERE company_id = ?", (company_id,))
        return [dict(row) for row in cur.fetchall()]

    def make_markdown_table(self, columns, rows):
        """Returns a Reddit Markdown table from a list of column names and row data."""
        out = " | ".join(columns) + "\n"
        out += " | ".join([":--"] * len(columns)) + "\n"
        for row in rows:
            out += " | ".join(row) + "\n"
        return out

    def make_comment_text(self, company_data, events):
        """Returns the response comment text."""
        event_columns = ['Terminart', 'Info', 'Datum']
        event_rows = []
        for e in events:
            event_rows.append([e['type'], e['info'], e['date']])

        body = "# {} Termine\n\n".format(company_data['name'])
        body += "*WKN: {} | ISIN: {} | Symbol: {}*\n\n".format(company_data['wkn'], company_data['isin'], company_data.get('symbol') if company_data.get('symbol') else '-')
        body += self.make_markdown_table(event_columns, event_rows)
        return body

    def scrape_events(self, company_search_string):
        """Returns company event data from finanzen.net"""
        log.debug("Scraping data for {}".format(company_search_string))
        # we don't want to scrape too fast
        time.sleep(random.random()*5)
        # query finanzen.net
        base_url = 'https://www.finanzen.net/termine/termine_suchergebnis.asp'
        res = self.session.get(
            base_url,
            params={
                'frmTermineSuche': company_search_string
            },
            headers={
                'User-Agent': random.choice(self.user_agent_list)
            }
        )

        # parse page elements
        dom = html.fromstring(res.content)
        copy_elements = dom.find_class('icon-copy')
        company_data = {e.get('cptxt').lower(): e.get('cpval') for e in copy_elements}
        if not ('wkn' in company_data and 'isin' in company_data):
            # no WKN or ISIN => no company found or search string
            raise Exception("Missing WKN or ISIN")

        title = dom.xpath('/html/body/div[2]/div[1]/div[2]/div[9]/div[1]/div[1]/div[1]/h2/text()')[0].strip()
        if title.endswith('Aktie'):
            company_data['name'] = title.replace('Aktie', '').strip()
        else:
            # skip if we can't extract the company name
            raise Exception("Not a stock")

        events_table = dom.xpath('/html/body/div[2]/div[1]/div[2]/div[13]/div[1]/div[1]/div/table')[0]
        columns = [x.strip() for x in events_table.xpath(".//thead/tr/th/text()")]
        parsed_events = []

        # parse rows of company events table
        for row in events_table.xpath(".//tr"):
            row_data = [x.text.strip() for x in row.xpath(".//td")]
            if len(row_data) > 0:
                zipped = dict(zip(columns, row_data))
                parsed_events.append({
                    'date': zipped.get('Datum'),
                    'type': zipped.get('Terminart'),
                    'info': zipped.get('Info')
                })

        if len(parsed_events) == 0:
            raise Exception("Found no events")

        return company_data, parsed_events

    def check_comment(self, comment):
        """Checks PRAW comment for bot trigger command and responds to comment if triggered."""
        command_regex = r"\!termine? \$?(\w{1,6}|[A-Za-z]{2}\d{10})(?:\s|$)"
        matches = set(re.findall(command_regex, comment.body, re.MULTILINE | re.IGNORECASE))

        if len(matches) > 0:
            # we found bot commands
            if self.already_responded(comment.id):
                log.debug("Already responded to comment {}".format(comment.id))
                return
            
            log.debug("New comment {} requesting events for {}".format(comment.id, matches))
            responses = []
            for match in matches:
                try:
                    company_data = self.get_company(match)
                    if company_data:
                        # we have found a company in our database
                        log.debug("Found company in db {}".format(company_data))
                        events = self.get_events(company_data['id'])
                        log.debug("Found {} events in db".format(len(events)))
                    
                    if not company_data or len(events) == 0:
                        # unknown company or we found no events for a known company
                        company_data, events = self.scrape_events(match)
                        # store scraped data in db
                        new_id = self.insert_company(company_data.get('name'), company_data.get('isin'), company_data.get('wkn'), company_data.get('symbol'))
                        for e in events:
                            self.insert_event(new_id, e['date'], e['type'], e['info'])
                    # a user can make multiple commands in one comment
                    responses.append(self.make_comment_text(company_data, events))
                except Exception as e:
                    log.error("An error occured processing the company identifier {}".format(match))
                    log.error(e)
                    log.error(traceback.format_exc())

            if len(responses) > 0:
                # concat multiple reponses and prepend bot disclaimer
                response_text = "\n\n".join(responses) 
            else:
                response_text = "**Ich konnte leider keine Termine für deine Anfrage finden :(**"
            response_text += "\n\nIch bin ein MSW Community Bot | Du findest meinen Code auf [https://github.com/msw-projects](https://github.com/msw-projects)"
            response_text += "\nRufe mich mit `!termine` und WKN, ISIN oder Symbol (z.B. `!termine 508810` oder `!termine AAPL`)"

            if self.args.dry_run:
                # don't reply on dry run
                log.debug("Dry Run - did not reply")
                return
            
            # reply to original comment and save comment id
            comment.reply(response_text)
            self.register_response(comment.id)
            log.debug("Replied to comment {}".format(comment.id))

    def start(self):
        log.debug("Listening for comments...")
        subreddit = self.reddit.subreddit("mauerstrassenwetten+CommunityBotTests")
        for comment in subreddit.stream.comments():
            self.check_comment(comment)

    def stop(self):
        log.debug("Stopping bot...")
        self.con.close()