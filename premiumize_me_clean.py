#!/usr/bin/env python3
import asyncio
import logging
import sys
import re

from premiumize_me_dl.premiumize_me_api import PremiumizeMeAPI


class PremiumizeMeCleaner:
    url = 'https://www.premiumize.me/api'
    prev_file = None

    def __init__(self, auth, event_loop=None, prev_file=''):
        self.api = PremiumizeMeAPI(auth, event_loop=event_loop)

        self.last_transfer_ids = []
        for file_location in [prev_file, '.prev_file.txt', '/tmp/prev_file.txt']:
            try:
                with open(file_location) as f:
                    self.last_transfer_ids = f.read().split('\n')
            except:
                pass

            try:
                self.prev_file = open(file_location, 'w+')
                break
            except (FileNotFoundError, PermissionError, TypeError) as f:
                print(file_location, f)
                pass

    async def close(self):
        await self.api.close()
        if self.prev_file and not self.prev_file.closed:
            self.prev_file.close()

    async def clean(self):
        transfers = [_ for _ in await self.api.get_transfers() if _.status != 'finished']

        failed = self.get_failed_transfers(transfers)
        stale = self.get_stale_transfers(transfers) if self.prev_file else []

        await asyncio.gather(*[asyncio.ensure_future(self.api.delete(transfer)) for transfer in failed+stale])

        self.write_transfers(transfers)

    def write_transfers(self, transfers):
        if self.prev_file is None or self.prev_file.closed:
            return

        self.prev_file.flush()
        for transfer in transfers:
            self.prev_file.write("{}\n".format(transfer.id))
        self.prev_file.close()

    @staticmethod
    def get_failed_transfers(transfers):
        failed_ = []
        for transfer in transfers:
            if transfer.status == 'error' and transfer.message.startswith('Could not add'):
                logging.info("{} is failed, deleting!".format(transfer.name))
                failed_.append(transfer)

        return failed_

    def get_stale_transfers(self, transfers):
        pttrn_ = re.compile(r'(?i)Downloading at 0 mbit/s from \d peers\. \d% of [\d.]+ \wB finished\. ETA is unknown')
        stale_ = []
        for transfer in transfers:
            if transfer.message is not None and (transfer.message == 'Loading...' or
                                                 re.match(pttrn_, transfer.message)):
                logging.info("{} is stale!".format(transfer.name))
                if str(transfer.id) in self.last_transfer_ids:
                    logging.info("\twas stale before, deleting".format(transfer.name))
                    stale_.append(transfer)

        return stale_

    def __bool__(self):
        return bool(self.api)


if __name__ == '__main__':
    import argparse
    from os import path, access, R_OK, W_OK

    def argcheck_file(string):
        if access(path.abspath(path.dirname(string)), W_OK) or (path.isfile(string) and
                                                                access(string, W_OK) and
                                                                access(string, R_OK)):
            return path.abspath(string)
        raise argparse.ArgumentTypeError('{} is no file or isn\'t writeable'.format(string))

    argparser = argparse.ArgumentParser(description="Cleans the transfers of your premiumize.me")
    argparser.add_argument('-p', '--previous', nargs='?', type=argcheck_file,
                           help='Choose a different location for the previous transfers')
    argparser.add_argument('-a', '--auth', type=str,
                           help="Either 'user:password' or a path to a pw-file with that format")

    args = argparser.parse_args()

    logging.basicConfig(format='%(message)s', level=logging.INFO)

    event_loop_ = asyncio.get_event_loop()
    dl = PremiumizeMeCleaner(args.auth, event_loop=event_loop_, prev_file=args.previous)
    if not dl:
        sys.exit(1)

    try:
        event_loop_.run_until_complete(dl.clean())
    except KeyboardInterrupt:
        pass
    finally:
        event_loop_.run_until_complete(dl.close())
