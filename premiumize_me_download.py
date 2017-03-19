#!/usr/bin/env python3
import datetime
import asyncio
import logging
import sys
import re

from premiumize_me_dl.premiumize_me_api import PremiumizeMeAPI


class PremiumizeMeDownloader:
    url = 'https://www.premiumize.me/api'

    def __init__(self, download_directory, auth, event_loop, delete_after_download_days=0):
        self.api = PremiumizeMeAPI(auth, event_loop)

        self.delete_after = datetime.timedelta(days=delete_after_download_days)
        self.download_directory = download_directory

    def close(self):
        self.api.close()

    @staticmethod
    def _parse_filters(filters):
        hashes = [f for f in filters if re.match(r'[0-9a-fA-F]{40}$', f)]
        regex = []
        if filters != hashes:
            regex = re.compile('|'.join(r for r in filters if r not in hashes), re.IGNORECASE)

        return regex, hashes

    async def download_files(self, filters):
        now = datetime.datetime.now()
        regex, hashes = self._parse_filters(filters)
        file_list = await self.api.get_files()
        for file_ in file_list:
            if file_.matches(regex, hashes):
                success = await self.api.download_file(file_, self.download_directory)
                if success and self.delete_after and file_.created_at+self.delete_after < now:
                    await self.api.delete(file_)

    async def upload_files(self, torrents):
        download_ids = [asyncio.ensure_future(self.api.upload(torrent)) for torrent in torrents]
        responses = await asyncio.gather(*download_ids)

        logging.info('Ids of uploaded files:')
        logging.info('\n'.join(map(str, responses)))
        return responses


if __name__ == '__main__':
    import argparse
    from os import path, access, W_OK, R_OK

    def argcheck_dir(string):
        if path.isdir(string) and access(string, W_OK) and access(string, R_OK):
            return path.abspath(string)
        raise argparse.ArgumentTypeError('{} is no directory or isn\'t writeable'.format(string))

    def argcheck_re(string):
        try:
            re.compile(string)
            return string
        except re.error:
            raise argparse.ArgumentTypeError('{} is no valid regular expression!'.format(string))

    argparser = argparse.ArgumentParser(description="Download your files at premiumize.me")
    argparser.add_argument('files', nargs='+', type=argcheck_re,
                           help='Download all files matching these (python) regular expressions.')
    argparser.add_argument('download_directory', type=argcheck_dir, default='.',
                           help='Set the directory to download the file(s) into.')
    argparser.add_argument('-a', '--auth', type=str, required=True,
                           help="Either 'user:password' or a path to a pw-file with that format")
    argparser.add_argument('-d', '--delete_after_download_days', type=int, default=0,
                           help="Delete files from My Files after successful download")
    argparser.add_argument('-u', '--upload', action='store_true',
                           help="Don't download files, but upload the given files")

    args = argparser.parse_args()

    logging.basicConfig(format='%(message)s',
                        level=logging.INFO)

    event_loop_ = asyncio.get_event_loop()
    dl = PremiumizeMeDownloader(args.download_directory, args.auth, event_loop_,
                                delete_after_download_days=args.delete_after_download_days)
    if not dl:
        sys.exit(1)

    try:
        if args.upload:
            event_loop_.run_until_complete(dl.upload_files(args.files))
        else:
            event_loop_.run_until_complete(dl.download_files(args.files))
    except KeyboardInterrupt:
        pass
    finally:
        dl.close()
        event_loop_.close()
