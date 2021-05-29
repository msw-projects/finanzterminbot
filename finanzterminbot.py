import os
import argparse
import traceback
import time
from logger import log
from bot import CompanyEventsBot
# load environment variables from .env
from dotenv import load_dotenv
load_dotenv()

def start_bot(args):
    bot = CompanyEventsBot(
        client_id=os.getenv('REDDIT_CLIENT_ID'),
        client_secret=os.getenv('REDDIT_CLIENT_SECRET'),
        username=os.getenv('REDDIT_USER'),
        password=os.getenv('REDDIT_PASSWORD'),
        args=args
    )

    bot.start()

def main():
    parser = argparse.ArgumentParser(
        description='Finanzterminbot - A /r/mauerstrassenwetten company events bot'
    )
    parser.add_argument('-v', '--verbose', action='store_true', help='verbose output')
    parser.add_argument('-r', '--restart', action='store_true', help='try to restart the bot if it encounters an unhandled exception')
    parser.add_argument('-d', '--dry-run', action='store_true', help='do not post to Reddit')
    args = parser.parse_args()

    if args.verbose:
        log.setLevel('DEBUG')
    
    try:
        start_bot(args)
    except Exception as e:
        log.error('An unhandled exception occured.')
        log.error(e)
        log.error(traceback.format_exc())
        if args.restart:
            log.error('Trying to restart bot in 120 seconds...')
            time.sleep(120)
            start_bot(args)

if __name__ == "__main__":
    main()