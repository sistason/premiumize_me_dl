import os
import json
import logging
import aiohttp
import asyncio
import getpass
import zipfile
import datetime
import subprocess
import concurrent.futures
from fuzzywuzzy import fuzz

from premiumizeme.objects import Transfer, Download, File, Folder, TransferSrc

# Premiumize.me API Version
__version__ = 3
logger = logging.getLogger(__name__)


class PremiumizeMeAPI:
    url = 'https://www.premiumize.me/api'
    CACHE_TIME = 5

    def __init__(self, auth, event_loop=None):
        self.event_loop = asyncio.get_event_loop() if event_loop is None else event_loop
        self.login_data = self._read_auth(auth)

        self.file_list_cached = None
        self.file_list_cache_valid_until = datetime.datetime.fromtimestamp(0)
        self.folder_list_cached = None
        self.folder_list_cache_valid_until = datetime.datetime.fromtimestamp(0)

        self.aiohttp_session = None

        self.max_simultaneous_downloads = asyncio.Semaphore(2)
        self.process_pool = concurrent.futures.ThreadPoolExecutor(4)

    async def close(self):
        if self.aiohttp_session is not None:
            await self.aiohttp_session.close()

    async def download(self, item, download_directory):
        if type(item) in [File, Download]:
            return await self.download_file(item, download_directory)
        if type(item) is Folder:
            return await self.download_folder(item, download_directory)
        if type(item) is Transfer:
            return await self.download_transfer(item, download_directory)
        else:
            logger.error('Unable to download "{}", unknown type'.format(item))
            return False

    async def download_transfer(self, transfer, download_directory):
        if not await self.wait_for_transfer(transfer):
            await self.delete(transfer)
            return

        for _ in range(5):
            transfer = await self.get_transfer(transfer.id)
            await asyncio.sleep(1)  # ???
            content = await self.get_content_from_transfer(transfer)
            if content:
                return self.download(content, download_directory)

    async def wait_for_transfer(self, transfer):
        start = datetime.datetime.now()
        logger.info('Waiting for premiumize.me to finish downloading the torrent "{}"...'.format(transfer.name))
        while await asyncio.sleep(2):
            transfer = await self.get_transfer(transfer.id)
            logger.info('  {} | Status: {}; Message: {}'.format('Run' if transfer.is_running() else 'Idle',
                                                                 transfer.status, transfer.message))
            if self.is_transfer_finished(transfer, start):
                return True

    @staticmethod
    def is_transfer_finished(transfer, start_time):
        if transfer is not None and transfer.is_running() and transfer.status != 'error':
            return None
        if transfer is not None and transfer.message == 'Loading...' and \
                (datetime.datetime.now() - start_time).seconds > 10 * 60:
            logger.error('Torrent {} didn\'t finish loading, aborted'.format(transfer.name))
            return False
        return True

    async def download_directdl(self, url, download_directory):
        response_text = await self._make_request('/transfer/directdl', data={'src': url})
        success, response_json = self._validate_to_json(response_text)
        if success:
            name = url.split('/')[-1]
            tasks = asyncio.gather(*[self.download_file(Download({'location': c.get('link')}, name), download_directory)
                                     for c in response_json.get('content', [])])
            await tasks
            return True
        else:
            logger.error('Could not get direct-download link {}: {}'.format(url, response_json.get('message')))
            return False

    async def download_file(self, item, download_directory):
        if type(item) is File or type(item) is Download:
            file = item
        else:
            logger.error('Don\'t know how to download "{}"'.format(item))
            return False

        if not download_directory.exists():
            os.makedirs(download_directory, exist_ok=True)

        if self._file_exists(file, download_directory):
            return True

        async with self.max_simultaneous_downloads:
            size_ = '({} MB)'.format(file.size_in_mb) if file.size_in_mb else ''
            logger.info('Downloading {}{}...'.format(file.get_full_path(), size_))

            file_destination = download_directory / file.name
            success = await self.event_loop.run_in_executor(self.process_pool,
                                                            self._download_file_wget_process,
                                                            file, file_destination)
            if file.type == 'generated-zip' and success:
                self._unzip(file_destination)

            return success

    async def download_folder(self, folder, download_directory):
        download_directory = download_directory / folder.name

        for content in await self.list_folder(folder):
            await self.download(content, download_directory)

    @staticmethod
    def _download_file_wget_process(file, file_destination):
        # --continue even though premiumize.me does not (yet?) implement it
        return subprocess.run(['wget', '--continue', '--show-progress', file.link, '-qO', file_destination]).returncode == 0

    async def upload(self, torrent):
        src = None
        if type(torrent) is str:
            src = torrent
        elif str(torrent.__class__).rsplit('.', 1)[-1].startswith('PirateBayResult'):
            src = torrent.magnet

        response_text = await self._make_request("/transfer/create", data={'src': src})
        success, response_json = self._validate_to_json(response_text)
        if success or response_json.get('message') == 'You already added this job.':
            src = TransferSrc(src)
            for transfer in await self.get_transfers(force=success):
                if transfer.src and (transfer.src.id == src.id or transfer.id == response_json.get("id")):
                    return transfer
                if transfer.name == src.name:
                    return transfer
            logger.debug("Transfer not found, getting nextbest...")

            levenshtein_ratios = [(transfer, fuzz.ratio(transfer.name.lower() if transfer.name else "", src.name.lower() if src.name else "")) for transfer in await self.get_transfers()]
            plausible = [t for t in levenshtein_ratios if t[1] > 80]
            if levenshtein_ratios and len(plausible) == 1:
                return levenshtein_ratios[0][0]
            
            logger.warning("Job not found in transfers?")

        logger.error('Could not upload torrent {}: {}'.format(torrent, response_json.get('message')))
        return

    async def delete(self, item_):
        if not item_ or not item_.id:
            return True
        if type(item_) is File:
            response_text = await self._make_request('/item/delete', data={'id': item_.id})
        elif type(item_) is Folder:
            response_text = await self._make_request('/folder/delete', data={'id': item_.id})
        elif type(item_) is Transfer:
            response_text = await self._make_request('/transfer/delete', data={'id': item_.id})
        else:
            logger.error('Unknown type of file to delete: {}'.format(item_))
            return True
        success, response_json = self._validate_to_json(response_text)
        if success:
            if type(item_) is Transfer:
                self.folder_list_cached = None
            else:
                self.file_list_cached = None
            return True

        logger.error('Could not delete file {}: {}'.format(item_, response_json.get('message')))
        return False

    async def get_content_from_transfer(self, transfer_):
        if type(transfer_) is not Transfer:
            return
        for file_ in await self.get_files():
            if (file_.type == 'folder' and file_.id == transfer_.folder_id) or \
               (file_.type == 'file' and file_.id == transfer_.file_id):
                return file_

        logger.error('No content for transfer "{}" found, status is: "{}"'.format(transfer_.name, transfer_.status_msg()))

    async def get_files(self, force=False):
        now = datetime.datetime.now()
        if self.file_list_cache_valid_until > now or force:
            self.file_list_cached = None
        if self.file_list_cached is None:
            self.file_list_cached = await self._update_files()

        return self.file_list_cached or []

    async def _update_files(self):
        folder_list = await self.list_folder()
        if folder_list:
            self.file_list_cache_valid_until = datetime.datetime.now() + datetime.timedelta(seconds=self.CACHE_TIME)
            return folder_list

    async def list_folder(self, folder=None):
        data = {'includebreadcrumbs': True}
        if folder:
            data['id'] = folder.id
        response_text = await self._make_request('/folder/list', data=data)
        success, response_json = self._validate_to_json(response_text)
        if success:
            file_list = []
            breadcrumbs = response_json.get('breadcrumbs', [])
            for properties_ in response_json.get('content', []):
                if not properties_:
                    continue
                if properties_.get('type', '') == 'file':
                    file_list.append(File(properties_, breadcrumbs))
                if properties_.get('type', '') == 'folder':
                    file_list.append(Folder(properties_, breadcrumbs))
            return file_list
        else:
            logger.error('Error while getting folder "{}". Was: {}'.format(folder, response_json.get('message')))
            return []

    """
    async def get_transfers(self, force=False):
        now = datetime.datetime.now()
        if self.transfer_list_cache_valid_until > now or force:
            self.transfer_list_cached = None
        if self.transfer_list_cached is None:
            self.transfer_list_cached = await self._update_transfers()

        return self.file_list_cached or []

    async def _update_transfers(self):
        transfer_list = await self.list_transfers()
        if transfer_list:
            self.transfer_list_cache_valid_until = datetime.datetime.now() + datetime.timedelta(seconds=self.CACHE_TIME)
            return transfer_list

    async def list_transfer(self, transfer=None):
        if transfer:
            folder = {'id': transfer.id}
        response_text = await self._make_request('/transfers/list', data=transfer)
        success, response_json = self._validate_to_json(response_text)
        if success:
            transfer_list = []
            for properties_ in response_json.get('content', []):
                if not properties_:
                    continue
                if properties_.get('type', '') == 'file':
                    transfer_list.append(File(properties_))
                if properties_.get('type', '') == 'folder':
                    transfer_list.append(Folder(properties_))
            return transfer_list
        else:
            logger.error('Error while getting folder "{}". Was: {}'.format(transfer, response_json.get('message')))
            return []
        """
    async def get_transfers(self, force=False):
        now = datetime.datetime.now()
        if self.folder_list_cache_valid_until > now or force:
            self.folder_list_cached = None
        if self.folder_list_cached is None:
            self.folder_list_cached = await self._update_transfers()

        return self.folder_list_cached or []

    async def get_transfer(self, id_):
        if type(id_) is Transfer:
            id_ = id_.id
        for transfer in await self.get_transfers():
            if id_ == transfer.id:
                return transfer

    async def _update_transfers(self):
        response_text = await self._make_request('/transfer/list')
        success, response_json = self._validate_to_json(response_text)
        if success:
            transfers = []
            for properties_ in response_json.get('transfers', []):
                transfer_ = Transfer(properties_)
                if transfer_.status in ['finished', 'error'] and not (transfer_.folder_id or transfer_.file_id):
                    await self.delete(transfer_)
                else:
                    transfers.append(transfer_)
            self.folder_list_cache_valid_until = datetime.datetime.now() + datetime.timedelta(seconds=self.CACHE_TIME)
            return transfers
        logger.error('Error while getting transfers. Was: {}'.format(response_json.get('message')))

    async def _make_request(self, url, data=None):
        """ Do a request, take care of the login, timeouts and exceptions """
        data_ = self.login_data
        if data is not None:
            data_.update(data)
        if self.aiohttp_session is None:
            self.aiohttp_session = aiohttp.ClientSession(loop=self.event_loop)

        retries = 3
        for _ in range(retries):
            try:
                async with self.aiohttp_session.post(self.url + url, data=data_, timeout=10) as r_:
                    text = await r_.text()
                    if r_.status == 200:
                        return text
                    else:
                        logger.error('Calling {} returned status code {}, retrying...'.format(url, r_.status))
            except (asyncio.TimeoutError, aiohttp.ClientConnectionError):
                logger.warning('Timeout, retrying...')

            except Exception as e:
                logger.error('Caught Exception "{}" while making a get-request to "{}"'.format(e.__class__, url))
                return json.dumps({'error': 'true', 'message': str(e)})

            await asyncio.sleep(1)
        return json.dumps({'error': 'true', 'message': 'timeout'})

    @staticmethod
    def _validate_to_json(response_text):
        response_json = json.loads(response_text)
        if response_json.get('status') == 'error':
            return False, response_json
        return True, response_json

    def _file_exists(self, file_, directory):
        path_ = os.path.join(directory, file_.name)
        if os.path.exists(path_) and file_.size > -1:
            try:
                if file_.size and file_.size * 0.999 < self._get_size(path_) < file_.size * 1.001:
                    logger.info('Skipped "{}", already exists'.format(file_.get_full_path()))
                    return True
            except OSError as e:
                logger.warning('Could not get size of file "{}": {}'.format(file_.get_full_path(), e))
        return False

    def _get_size(self, path_):
        if not os.path.isdir(path_):
            return os.path.getsize(path_)
        return sum(self._get_size(entry.path) for entry in os.scandir(path_))

    @staticmethod
    def _unzip(file_destination):
        if not file_destination.endswith('.zip'):
            return
        try:
            z = zipfile.ZipFile(file_destination)
            z.extractall(path=os.path.dirname(file_destination))
            os.remove(file_destination)
        except zipfile.error as e:
            logger.warning('Unzipping of "{}" failed: {}'.format(file_destination, e))

    @staticmethod
    def _read_auth(auth):
        if not auth:
            auth = os.path.join(os.path.expanduser('~'), '.premiumize_me_auth.txt')

        if ':' in auth:
            username, password = auth.strip().split(':')
        elif os.path.exists(auth):
            with open(auth, 'r') as f:
                username, password = f.read().strip().split(':')
        else:
            with open(auth, 'w') as f:
                username = input('Please enter your premiumize.me-username: ')
                password = getpass.getpass(prompt='Please enter your premiumize.me-password: ')
                f.write(':'.join([username, password]))

        if not (username and password):
            logger.error('Authentication file not found or credentials were malformed!')
            return {}

        return {'customer_id': username, 'pin': password}

    def __bool__(self):
        return bool(self.login_data.get('customer_id') and self.login_data.get('pin'))
