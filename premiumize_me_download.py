#!/usr/bin/env python
import logging


class PremiumizeMeDownloader:
    def __init__(self, *args, **kwargs):
        pass

if __name__ == '__main__':
    import argparse
    from os import path, access, W_OK, R_OK

    def argcheck_dir(string):
        if path.isdir(string) and access(string, W_OK) and access(string, R_OK):
            return path.abspath(string)
        raise argparse.ArgumentTypeError('%s is no directory or isn\'t writeable' % string)

    argparser = argparse.ArgumentParser(description="Download files from your files at premiumize.me")

    argparser.add_argument('files', nargs='*',
                           help='Download the files with that matching regex.')
    argparser.add_argument('download_directory', type=argcheck_dir, default='.',
                           help='Set the directory to download the file(s) into.')
    argparser.add_argument('-d', '--delete_after_download', action="store_true",
                           help="Delete files from My Files after download")

    args = argparser.parse_args()

    dl = PremiumizeMeDownloader(vars(args))
    logging.basicConfig(format='%(funcName)-23s: %(message)s',
                        level=logging.DEBUG)