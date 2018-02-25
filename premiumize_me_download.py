#!/usr/bin/env python3
import datetime
import asyncio
import logging
import sys
import re

from premiumize_me_dl.premiumize_me_api import PremiumizeMeAPI


class PremiumizeMeDownloader:
    url = 'https://www.premiumize.me/api'

    def __init__(self, download_directory, auth, event_loop=None, delete_after_download_days=-1, cleanup=False):
        self.event_loop = asyncio.get_event_loop() if event_loop is None else event_loop
        self.api = PremiumizeMeAPI(auth, event_loop=self.event_loop)

        self.delete_after = datetime.timedelta(days=delete_after_download_days)
        self.only_cleanup = cleanup
        self.download_directory = download_directory

    def close(self):
        self.api.close()

    async def download_files(self, filter_regex):
        regex = re.compile(filter_regex, re.IGNORECASE)
        file_list = await self.api.get_files()
        tasks = asyncio.gather(*[self._download_file(file_) for file_ in file_list if file_.matches(regex)])
        await tasks

    async def _download_file(self, file_):
        if self.only_cleanup:
            success = True
        else:
            success = await self.api.download_file(file_, self.download_directory)

        if success:
            await self._cleanup_item(file_)
        else:
            logging.error('Could not download "{}"'.format(file_.name))

    async def _cleanup_item(self, item):
        now = datetime.datetime.now()
        if self.delete_after.days < 0:
            return

        # Check if the file is old enough to delete or
        # if a folder is old enough, by checking if a file in that folder is old enough.
        if item.type == 'file' and item.created_at + self.delete_after < now or \
           item.type == 'folder' and [i for i in await self.api.list_folder(item) if
                                      i.type == 'file' and i.created_at + self.delete_after > now]:
            await self.api.delete(item)

    def __bool__(self):
        return bool(self.api)


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
    argparser.add_argument('file_regex', type=argcheck_re,
                           help='Download all files matching this (python) regular expression.')
    argparser.add_argument('download_directory', type=argcheck_dir, default='.', nargs='?',
                           help='Set the directory to download the file(s) into.')
    argparser.add_argument('-a', '--auth', type=str,
                           help="Either 'user:password' or a path to a pw-file with that format")
    argparser.add_argument('-d', '--delete_after_download_days', type=int, default=-1,
                           help="Delete files from My Files after successful download")
    argparser.add_argument('-c', '--cleanup', action='store_true',
                           help="Don't download files, just cleanup. Use with -d")

    args = argparser.parse_args()

    logging.basicConfig(format='%(message)s',
                        level=logging.INFO)

    event_loop_ = asyncio.get_event_loop()
    dl = PremiumizeMeDownloader(args.download_directory, args.auth, event_loop_,
                                delete_after_download_days=args.delete_after_download_days,
                                cleanup=args.cleanup)
    if not dl:
        sys.exit(1)

    try:
        event_loop_.run_until_complete(dl.download_files(args.file_regex))
    except KeyboardInterrupt:
        pass
    finally:
        dl.close()
