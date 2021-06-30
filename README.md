# premiumize.me.dl
Download/Upload your premiumize.me torrents via cli

## Usage
### Download files from your account

`python3 premiumize_me_download.py file_regex []/your/download/path] [-a auth] [-d days] [-c]`
 - file_regex: Regular expression for which files to get
 - -a: Supply authentication information. These can be either:
   - A string in the format "user:pass"
   - A file-path containing "user:pass"
   - Default: it looks for a .premiumize_me_auth.txt in the home directory, otherwise asks.
 - -d, --delete: Delete downloaded $files, if they are older than $day days.
 - -c, --cleanup: Ignore $files, just delete all files older than $days.


### Upload links to your account

`python3 premiumize_me_upload.py link [link, ...] [-a auth]`
 - link: Anything the premiumize.me downloader likes (pirate-bay-url, magnet, ...)
 - -a: Supply authentication information. <see above>
   

## Dependencies
 - python 3.5+ (asyncio)
 - python3-aiohttp
 - A valid premiumize.me account with Premium ;)
