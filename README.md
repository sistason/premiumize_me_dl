# premiumize.me.dl
Downloads your premiumize.me downloaded files ("My Files") via cli

## Usage
python3 premiumize_me_download.py files [files, ...] dir [-a auth] [-d]
 - files: Regular expressions for which files to get
 - dir: Directory to download files to
 - -a: Supply authentication information. These can be either:
   - A string in the format "user:pass"
   - A file containing "user:pass"
 - -d: Set to delete successfully downloaded files from premiumize.me
 
 ## Dependencies
 - python3
 - python3-requests
 - python3-tqdm (via pip)
 - A valid premiumize.me account with Premium ;)