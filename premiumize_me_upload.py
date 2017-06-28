#!/usr/bin/env python3
import asyncio
import logging
import sys

from premiumize_me_dl.premiumize_me_api import PremiumizeMeAPI


class PremiumizeMeUploader:
    url = 'https://www.premiumize.me/api'

    def __init__(self, auth, event_loop):
        self.api = PremiumizeMeAPI(auth, event_loop)

    def close(self):
        self.api.close()

    async def upload_files(self, torrents):
        download_ids = [asyncio.ensure_future(self.api.upload(torrent)) for torrent in torrents]
        responses = await asyncio.gather(*download_ids)

        logging.info('Ids of uploaded files:')
        logging.info('\n'.join(map(str, responses)))
        return responses

    def __bool__(self):
        return bool(self.api)


if __name__ == '__main__':
    import argparse

    argparser = argparse.ArgumentParser(description="Upload links to your premiumize.me")
    argparser.add_argument('files', nargs='+', type=str,
                           help='Let premiumize.me download these links to your cloud')
    argparser.add_argument('-a', '--auth', type=str, required=True,
                           help="Either 'user:password' or a path to a pw-file with that format")

    args = argparser.parse_args()

    logging.basicConfig(format='%(message)s',
                        level=logging.INFO)

    event_loop_ = asyncio.get_event_loop()
    dl = PremiumizeMeUploader(args.auth, event_loop_)
    if not dl:
        sys.exit(1)

    try:
        event_loop_.run_until_complete(dl.upload_files(args.files))
    except KeyboardInterrupt:
        pass
    finally:
        dl.close()
        event_loop_.close()