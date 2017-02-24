#!/usr/bin/env python
import datetime
import requests
import logging
import zipfile
import shutil
import time
import json
import sys
import os
import re


class File:
    def __init__(self, properties):
        try:
            self.id = int(properties.get('id', 0))
            self.hash = properties.get('hash', '')
            self.size = int(properties.get('size', 0))
            self.size_in_mb = int(self.size/1024/1024)
            self.name = properties.get('name', '')
            self.created_at = datetime.datetime.fromtimestamp(int(properties.get('created_at', 0)))
            self.type = properties.get('type', '')
        except (ValueError, IndexError, AttributeError):
            del self
            return

    def __str__(self):
        return '{s.id}: {s.name} ({s.size}byte)'.format(s=self)


class PremiumizeMeDownloader:
    def __init__(self, download_directory, delete_after_download=False, auth=''):
        logging.getLogger("requests").setLevel(logging.WARNING)
        self.delete_after_download = delete_after_download
        self.download_directory = download_directory

        self.username, self.password = self._read_auth(auth)
        if not self.username:
            sys.exit(1)
        self.login_data = {'customer_id': self.username, 'pin': self.password}

    @staticmethod
    def _read_auth(auth):
        if auth and os.path.exists(auth):
            with open(auth, 'r') as f:
                auth = f.read()

        if not (auth and ':' in auth):
            logging.error('No ":" found in authentication information, login not possible!')
            return None, None

        username, password = auth.strip().split(':')
        return username, password

    def _make_request(self, url, data=None):
        """ Do a request, take care of the cookies, timeouts and exceptions """
        data_ = self.login_data
        if data is not None:
            data_.update(data)
        ret = ''
        retries = 3
        while not ret and retries > 0:
            try:
                r_ = requests.post(url, data=data_, timeout=2)
                ret = r_.text
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                retries -= 1
                time.sleep(1)
            except Exception as e:
                logging.debug('Caught Exception "{}" while making a get-request to "{}"'.format(e.__class__, url))
                break
        return ret

    def download_files(self, file_regexes):
        search_re = re.compile(r'(?i){}'.format('|'.join(file_regexes)))
        files_deleted = []
        file_list = self._get_list_of_files()
        for file_ in file_list:
            if search_re.search(file_.name):
                success = self._download_file(file_)
                if success and self.delete_after_download:
                    self._delete_file(file_)
                    files_deleted.append(file_)

        if self.delete_after_download:
            [file_list.remove(d) for d in files_deleted]
            logging.info('Remaining files in "My Files":  {}'.format(file_list))

    def _get_list_of_files(self):
        ret = self._make_request('https://www.premiumize.me/api/folder/list')
        ret_j = json.loads(ret)
        if 'error' in ret_j:
            logging.error('Error while getting file-list. Was: {}'.format(ret_j.get('message')))
            return []

        return [File(properties_) for properties_ in ret_j.get('content', []) if properties_]

    def _download_file(self, file_):
        path_ = os.path.join(self.download_directory, file_.name)
        if os.path.exists(path_):
            try:
                if file_.size * 0.999 < self._get_size(path_) < file_.size * 1.001:
                    logging.info('Skipped "{}",get already exists'.format(file_.name))
                    return True
            except OSError as e:
                logging.warning('Could not get size of file "{}": {}'.format(file_.name, e))

        ret = self._make_request('https://www.premiumize.me/api/torrent/browse?hash={}'.format(file_.hash))
        ret_j = json.loads(ret)

        zip_dl_link = ret_j.get('zip', '')
        if  not zip_dl_link or ret_j.get('status','') == 'error':
            logging.warning('Could not download file "{}": {}'.format(file_.name, ret_j.get('message', '')))
            return False

        logging.info('Downloading {} ({} MB)...'.format(file_.name+'.zip', file_.size_in_mb))
        return self._download(file_, zip_dl_link)

    def _download(self, file_, link):
        start_time = time.time()
        r = requests.get(link, data=self.login_data, stream=True)
        if r.ok:
            file_destination = os.path.join(self.download_directory, file_.name+'.zip')
            with open(file_destination, 'wb') as f:
                # FIXME: PYSSL-bug, unimaginably slow with iter_content() and https. So no progress-bar :(
                # import tqdm
                # for data in tqdm(r.iter_content(), total=file_.size, unit='B', unit_scale=True):
                r.raw.decode_content = True
                shutil.copyfileobj(r.raw, f)

            try:
                z = zipfile.ZipFile(file_destination)
                z.extractall(path=self.download_directory)
                os.remove(file_destination)
            except Exception:
                pass

            transfer_time = time.time() - start_time
            logging.info('Download finished, took {:2}s, at {:2}MB/s'.format(
                transfer_time, file_.size_in_mb/transfer_time))
            return True
        else:
            logging.error('Download of "{}" failed, returned "{}"!'.format(link, r.status_code))
            return False

    def _delete_file(self, file_):
        ret = self._make_request('https://www.premiumize.me/api/item/delete?type={}&id={}'.format(file_.type, file_.id))
        if 'success' in ret:
            return True
        logging.error('Could not delete file {}: {}'.format(file_, ret))

    def _get_size(self, path_):
        if not os.path.isdir(path_):
            return os.path.getsize(path_)
        return sum(self._get_size(entry.path) for entry in os.scandir(path_))

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
    argparser.add_argument('-d', '--delete_after_download', action="store_true",
                           help="Delete files from My Files after successful download")
    argparser.add_argument('-a', '--auth', type=str,
                           help="Either 'user:password' or a path to a pw-file with that format")

    args = argparser.parse_args()

    logging.basicConfig(format='%(message)s',
                        level=logging.INFO)

    dl = PremiumizeMeDownloader(args.download_directory,
                                delete_after_download=args.delete_after_download, auth=args.auth)
    dl.download_files(args.files)
