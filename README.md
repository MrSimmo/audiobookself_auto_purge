# AudioBookShelf Auto Purge

As of the time of creating this, AudioBookShelf doesnt have the ability to automatically delete/purge/remove items from the library when they've been finished listening to. 

This means that finished podcast episodes etc take up disk space which could be freed up.

This python script connects via the API to ABS to check for finished Podcast episodes and then delete them. 

Note - you can also keep ABS podcast shows by adding the tag "KEEP" (without the quotes) to the shows tag. The script will ignore shows that have that tag.


I run it as a cronjob on my server but you can run it however you like.

Environment variables are:

DRY_RUN       (0 or 1). 1 being it checked but doesn't actually delete anything
ABS_URL       the url of your ABS server
ABS_TOKEN     your API key (generated from settings -> api keys) in your ABS server)
VERIFY_SSL    (0 or 1). You can bypass the SSL certificate check by setting this to 0. If you see it failing, try this.
MEDIA_TYPE    EVERYTHING or AUDIOBOOKS or PODCASTS. Search for everything or just podcasts or just audiobooks.
DEBUG         (0 or 1). 1 enables extra logging for error remediation.


Here is my command line that I use on my mac:

DRY_RUN=1 ABS_URL="https://my_nas_server:13370/audiobookshelf" ABS_TOKEN="abs_api_key" VERIFY_SSL=0 python3 ./abs-cleanup-finished-episodes-v3.py



Example cron entry (runs daily at 3am):

0 3 * * * ABS_URL="https://my_nas_server:13370/audiobookshelf" ABS_TOKEN="your-token" /path/to/abs-cleanup-finished-episodes-v3.py
