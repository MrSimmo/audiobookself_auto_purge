#!/usr/bin/env python3
"""
Audiobookshelf Finished Media Cleanup (v4)

Polls the ABS API for finished podcast episodes and/or audiobooks and deletes
them from both ABS and disk. Intended to run as a cron job.

Podcasts/Audiobooks with a "KEEP" tag will be skipped entirely.

Usage:
    ./abs-cleanup-finished-episodes-v4.py

Environment variables:
    ABS_URL     - Base URL of your Audiobookshelf instance
    ABS_TOKEN   - API token (find in ABS web UI: Settings -> Users -> click your user)
    VERIFY_SSL  - Set to 0 to skip SSL cert verification (for self-signed certs)
    DRY_RUN     - Set to 1 to preview deletions without actually deleting
    DEBUG       - Set to 1 for verbose logging
    MEDIA_TYPE  - What to clean up: PODCASTS, AUDIOBOOKS, or EVERYTHING (default: EVERYTHING)
    AGE         - Optional minimum age filter. Only delete items added to library at least this long ago.
                  Format: number + suffix (d=days, w=weeks, m=months, y=years)
                  Examples: 5d (5 days), 4w (4 weeks), 3m (3 months), 1y (1 year)

Pass the env variables first when running using bash/zsh etc:
    DRY_RUN=1 ABS_URL="https://my_server:13378/audiobookshelf" ABS_TOKEN="my_api_key" MEDIA_TYPE=EVERYTHING VERIFY_SSL=0 python3 ./abs-cleanup-finished-episodes-v4.py

Example with AGE filter (only delete items added 3+ months ago):
    AGE=3m ABS_URL="https://my_server:13378/audiobookshelf" ABS_TOKEN="my_api_key" python3 ./abs-cleanup-finished-episodes-v4.py

Example cron (daily at 3am):
    0 3 * * * ABS_URL="https://my_server:13378/audiobookshelf" ABS_TOKEN="your-token" MEDIA_TYPE="PODCASTS" /path/to/abs-cleanup-finished-episodes-v4.py
"""

import os
import sys
import re
import logging
import requests
from datetime import datetime, timedelta

# Configure logging
log_level = logging.DEBUG if os.environ.get('DEBUG', '').lower() in ('1', 'true', 'yes') else logging.INFO
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def parse_age(age_str: str) -> timedelta | None:
    """
    Parse an age string into a timedelta.

    Args:
        age_str: Age string in format like '5d', '4w', '3m', '1y'
                 d=days, w=weeks, m=months, y=years

    Returns:
        timedelta representing the age, or None if invalid
    """
    if not age_str:
        return None

    age_str = age_str.strip().lower()
    match = re.match(r'^(\d+)\s*([dwmy])$', age_str)

    if not match:
        return None

    value = int(match.group(1))
    unit = match.group(2)

    if unit == 'd':
        return timedelta(days=value)
    elif unit == 'w':
        return timedelta(weeks=value)
    elif unit == 'm':
        # Approximate months as 30 days
        return timedelta(days=value * 30)
    elif unit == 'y':
        # Approximate years as 365 days
        return timedelta(days=value * 365)

    return None


def is_old_enough(added_at_ms: int, min_age: timedelta) -> bool:
    """
    Check if an item is old enough based on when it was added.

    Args:
        added_at_ms: Timestamp in milliseconds when item was added
        min_age: Minimum age as a timedelta

    Returns:
        True if the item is at least min_age old, False otherwise
    """
    if not added_at_ms:
        # If no addedAt timestamp, assume it's old enough (conservative approach)
        return True

    added_at = datetime.fromtimestamp(added_at_ms / 1000)
    age = datetime.now() - added_at

    return age >= min_age


class ABSClient:
    def __init__(self, base_url: str, token: str, verify_ssl: bool = True):
        self.base_url = base_url.rstrip('/')
        self.verify_ssl = verify_ssl
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        })

        if not verify_ssl:
            # Suppress the InsecureRequestWarning
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _get(self, endpoint: str, params: dict = None) -> dict:
        url = f"{self.base_url}{endpoint}"
        response = self.session.get(url, params=params, verify=self.verify_ssl)
        response.raise_for_status()
        return response.json()

    def _delete(self, endpoint: str, params: dict = None) -> requests.Response:
        url = f"{self.base_url}{endpoint}"
        response = self.session.delete(url, params=params, verify=self.verify_ssl)
        response.raise_for_status()
        return response

    def get_user_with_progress(self) -> dict:
        """Get current user info including media progress."""
        return self._get('/api/me')

    def get_libraries(self) -> list:
        """Get all libraries."""
        data = self._get('/api/libraries')
        return data.get('libraries', [])

    def get_podcast_libraries(self) -> list:
        """Get only podcast-type libraries."""
        return [lib for lib in self.get_libraries() if lib.get('mediaType') == 'podcast']

    def get_book_libraries(self) -> list:
        """Get only book-type libraries (audiobooks)."""
        return [lib for lib in self.get_libraries() if lib.get('mediaType') == 'book']

    def get_library_items(self, library_id: str) -> list:
        """Get all items in a library."""
        data = self._get(f'/api/libraries/{library_id}/items')
        return data.get('results', [])

    def get_library_item(self, library_item_id: str) -> dict:
        """Get a single library item with full details including episodes."""
        return self._get(f'/api/items/{library_item_id}', params={'expanded': '1'})

    def delete_episode(self, library_item_id: str, episode_id: str, hard_delete: bool = True) -> bool:
        """
        Delete a podcast episode.

        Args:
            library_item_id: The podcast's library item ID
            episode_id: The episode ID to delete
            hard_delete: If True, also delete the file from disk

        Returns:
            True if successful
        """
        params = {'hard': '1'} if hard_delete else {}
        self._delete(f'/api/podcasts/{library_item_id}/episode/{episode_id}', params=params)
        return True

    def delete_library_item(self, library_item_id: str, hard_delete: bool = True) -> bool:
        """
        Delete a library item (audiobook).

        Args:
            library_item_id: The library item ID to delete
            hard_delete: If True, also delete the files from disk

        Returns:
            True if successful
        """
        params = {'hard': '1'} if hard_delete else {}
        self._delete(f'/api/items/{library_item_id}', params=params)
        return True


def get_finished_media(user_data: dict) -> tuple[set, set]:
    """
    Extract finished media from user's media progress.

    Returns:
        tuple of (finished_episode_ids, finished_audiobook_ids)
        - finished_episode_ids: set of episode IDs (for podcasts)
        - finished_audiobook_ids: set of library item IDs (for audiobooks)
    """
    finished_episodes = set()
    finished_audiobooks = set()

    for progress in user_data.get('mediaProgress', []):
        if progress.get('isFinished'):
            if progress.get('episodeId'):
                # This is a podcast episode
                finished_episodes.add(progress['episodeId'])
            elif progress.get('libraryItemId'):
                # This is an audiobook (no episodeId means it's a book)
                finished_audiobooks.add(progress['libraryItemId'])

    return finished_episodes, finished_audiobooks


def build_episode_map(client: ABSClient) -> dict:
    """
    Build a mapping of episode_id -> (library_item_id, podcast_title, episode_title, added_at).

    Scans all podcast libraries and their episodes.
    Skips podcasts that have a "KEEP" tag.
    """
    episode_map = {}

    for library in client.get_podcast_libraries():
        library_id = library['id']
        library_name = library['name']
        logger.info(f"Scanning podcast library: {library_name}")

        items = client.get_library_items(library_id)
        logger.debug(f"Found {len(items)} podcasts in library")

        for item in items:
            library_item_id = item['id']

            # Fetch full item details to get episodes
            try:
                full_item = client.get_library_item(library_item_id)
                media = full_item.get('media', {})
            except Exception as e:
                logger.warning(f"Failed to fetch details for {library_item_id}: {e}")
                continue

            podcast_title = media.get('metadata', {}).get('title', 'Unknown Podcast')

            # Check for KEEP tag - skip this podcast if found
            tags = media.get('tags', [])
            if 'KEEP' in tags:
                logger.info(f"  Skipping '{podcast_title}' - has KEEP tag")
                continue

            episodes = media.get('episodes', [])

            logger.debug(f"  {podcast_title}: {len(episodes)} episodes")

            for episode in episodes:
                episode_id = episode.get('id')
                episode_title = episode.get('title', 'Unknown Episode')
                added_at = episode.get('addedAt')

                if episode_id:
                    episode_map[episode_id] = {
                        'library_item_id': library_item_id,
                        'podcast_title': podcast_title,
                        'episode_title': episode_title,
                        'added_at': added_at
                    }

    return episode_map


def build_audiobook_map(client: ABSClient, finished_audiobook_ids: set) -> dict:
    """
    Build a mapping of library_item_id -> audiobook info for finished audiobooks.

    Only includes audiobooks that are in the finished set AND exist in a book library.
    Skips audiobooks that have a "KEEP" tag.
    """
    audiobook_map = {}

    for library in client.get_book_libraries():
        library_id = library['id']
        library_name = library['name']
        logger.info(f"Scanning audiobook library: {library_name}")

        items = client.get_library_items(library_id)
        logger.debug(f"Found {len(items)} audiobooks in library")

        for item in items:
            library_item_id = item['id']

            # Only process if this audiobook is in our finished set
            if library_item_id not in finished_audiobook_ids:
                continue

            # Fetch full item details
            try:
                full_item = client.get_library_item(library_item_id)
                media = full_item.get('media', {})
            except Exception as e:
                logger.warning(f"Failed to fetch details for {library_item_id}: {e}")
                continue

            audiobook_title = media.get('metadata', {}).get('title', 'Unknown Audiobook')
            author_name = media.get('metadata', {}).get('authorName', 'Unknown Author')

            # Check for KEEP tag - skip this audiobook if found
            tags = media.get('tags', [])
            if 'KEEP' in tags:
                logger.info(f"  Skipping '{audiobook_title}' - has KEEP tag")
                continue

            logger.debug(f"  Found finished audiobook: {audiobook_title}")

            # Get addedAt from the full_item (library item level)
            added_at = full_item.get('addedAt')

            audiobook_map[library_item_id] = {
                'library_item_id': library_item_id,
                'audiobook_title': audiobook_title,
                'author_name': author_name,
                'added_at': added_at
            }

    return audiobook_map


def main():
    # Load configuration from environment
    base_url = os.environ.get('ABS_URL')
    token = os.environ.get('ABS_TOKEN')

    # Also support a config file approach
    if not base_url or not token:
        config_path = os.path.expanduser('~/.config/abs-cleanup.env')
        if os.path.exists(config_path):
            logger.info(f"Loading config from {config_path}")
            with open(config_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        os.environ.setdefault(key.strip(), value.strip().strip('"\''))
            base_url = os.environ.get('ABS_URL')
            token = os.environ.get('ABS_TOKEN')

    if not base_url or not token:
        logger.error("Missing required configuration. Set ABS_URL and ABS_TOKEN environment variables,")
        logger.error("or create ~/.config/abs-cleanup.env with:")
        logger.error('  ABS_URL="http://myserver:13378/audiobookshelf"')
        logger.error('  ABS_TOKEN="your-api-token"')
        sys.exit(1)

    # Dry run mode
    dry_run = os.environ.get('DRY_RUN', '').lower() in ('1', 'true', 'yes')
    if dry_run:
        logger.info("DRY RUN MODE - no media will actually be deleted")

    # SSL verification (disable for self-signed certs)
    verify_ssl = os.environ.get('VERIFY_SSL', '1').lower() not in ('0', 'false', 'no')
    if not verify_ssl:
        logger.warning("SSL verification disabled")

    # Media type to process
    media_type = os.environ.get('MEDIA_TYPE', 'EVERYTHING').upper()
    if media_type not in ('PODCASTS', 'AUDIOBOOKS', 'EVERYTHING'):
        logger.error(f"Invalid MEDIA_TYPE: {media_type}. Must be PODCASTS, AUDIOBOOKS, or EVERYTHING")
        sys.exit(1)
    logger.info(f"Media type filter: {media_type}")

    # Age filter (optional)
    age_str = os.environ.get('AGE', '').strip()
    min_age = None
    if age_str:
        min_age = parse_age(age_str)
        if min_age is None:
            logger.error(f"Invalid AGE format: '{age_str}'. Use format like: 5d, 4w, 3m, 1y")
            logger.error("  d=days, w=weeks, m=months, y=years")
            sys.exit(1)
        logger.info(f"Age filter: only deleting items added {age_str} or more ago")

    process_podcasts = media_type in ('PODCASTS', 'EVERYTHING')
    process_audiobooks = media_type in ('AUDIOBOOKS', 'EVERYTHING')

    logger.info(f"Connecting to Audiobookshelf at {base_url}")
    client = ABSClient(base_url, token, verify_ssl=verify_ssl)

    # Get user's finished media
    logger.info("Fetching user progress data...")
    try:
        user_data = client.get_user_with_progress()
    except requests.exceptions.HTTPError as e:
        logger.error(f"Failed to authenticate. Check your API token. Error: {e}")
        sys.exit(1)

    finished_episode_ids, finished_audiobook_ids = get_finished_media(user_data)

    if process_podcasts:
        logger.info(f"Found {len(finished_episode_ids)} finished podcast episodes in progress data")
    if process_audiobooks:
        logger.info(f"Found {len(finished_audiobook_ids)} finished audiobooks in progress data")

    # Track totals
    total_deleted = 0
    total_failed = 0
    total_skipped_age = 0

    # Process podcast episodes
    if process_podcasts and finished_episode_ids:
        logger.info("=" * 50)
        logger.info("PROCESSING PODCAST EPISODES")
        logger.info("=" * 50)

        # Build map of all episodes across all podcast libraries
        logger.info("Building episode map from podcast libraries...")
        episode_map = build_episode_map(client)
        logger.info(f"Found {len(episode_map)} total episodes across all podcasts")

        # Find finished episodes that still exist
        episodes_to_delete = []
        for episode_id in finished_episode_ids:
            if episode_id in episode_map:
                ep_data = episode_map[episode_id]

                # Check age filter if configured
                if min_age is not None:
                    if not is_old_enough(ep_data.get('added_at'), min_age):
                        added_at_str = "unknown"
                        if ep_data.get('added_at'):
                            added_at_dt = datetime.fromtimestamp(ep_data['added_at'] / 1000)
                            added_at_str = added_at_dt.strftime('%Y-%m-%d')
                        logger.debug(f"  Skipping '{ep_data['episode_title']}' - too recent (added {added_at_str})")
                        total_skipped_age += 1
                        continue

                episodes_to_delete.append({
                    'episode_id': episode_id,
                    **ep_data
                })

        if episodes_to_delete:
            logger.info(f"Found {len(episodes_to_delete)} finished episodes to delete:")
            for ep in episodes_to_delete:
                logger.info(f"  - {ep['podcast_title']}: {ep['episode_title']}")

            # Delete episodes
            for ep in episodes_to_delete:
                try:
                    if dry_run:
                        logger.info(f"[DRY RUN] Would delete: {ep['podcast_title']} - {ep['episode_title']}")
                        total_deleted += 1
                    else:
                        logger.info(f"Deleting: {ep['podcast_title']} - {ep['episode_title']}")
                        client.delete_episode(ep['library_item_id'], ep['episode_id'], hard_delete=True)
                        total_deleted += 1
                        logger.info(f"  ✓ Deleted successfully")
                except requests.exceptions.HTTPError as e:
                    logger.error(f"  ✗ Failed to delete: {e}")
                    total_failed += 1
                except Exception as e:
                    logger.error(f"  ✗ Unexpected error: {e}")
                    total_failed += 1
        else:
            logger.info("No finished podcast episodes found that need deletion")

    # Process audiobooks
    if process_audiobooks and finished_audiobook_ids:
        logger.info("=" * 50)
        logger.info("PROCESSING AUDIOBOOKS")
        logger.info("=" * 50)

        # Build map of finished audiobooks that exist and don't have KEEP tag
        logger.info("Building audiobook map from book libraries...")
        audiobook_map = build_audiobook_map(client, finished_audiobook_ids)
        logger.info(f"Found {len(audiobook_map)} finished audiobooks eligible for deletion")

        # Apply age filter if configured
        audiobooks_to_delete = {}
        if min_age is not None:
            for lib_item_id, ab_data in audiobook_map.items():
                if is_old_enough(ab_data.get('added_at'), min_age):
                    audiobooks_to_delete[lib_item_id] = ab_data
                else:
                    added_at_str = "unknown"
                    if ab_data.get('added_at'):
                        added_at_dt = datetime.fromtimestamp(ab_data['added_at'] / 1000)
                        added_at_str = added_at_dt.strftime('%Y-%m-%d')
                    logger.debug(f"  Skipping '{ab_data['audiobook_title']}' - too recent (added {added_at_str})")
                    total_skipped_age += 1
        else:
            audiobooks_to_delete = audiobook_map

        if audiobooks_to_delete:
            logger.info(f"Audiobooks to delete:")
            for ab in audiobooks_to_delete.values():
                logger.info(f"  - {ab['audiobook_title']} by {ab['author_name']}")

            # Delete audiobooks
            for ab in audiobooks_to_delete.values():
                try:
                    if dry_run:
                        logger.info(f"[DRY RUN] Would delete: {ab['audiobook_title']} by {ab['author_name']}")
                        total_deleted += 1
                    else:
                        logger.info(f"Deleting: {ab['audiobook_title']} by {ab['author_name']}")
                        client.delete_library_item(ab['library_item_id'], hard_delete=True)
                        total_deleted += 1
                        logger.info(f"  ✓ Deleted successfully")
                except requests.exceptions.HTTPError as e:
                    logger.error(f"  ✗ Failed to delete: {e}")
                    total_failed += 1
                except Exception as e:
                    logger.error(f"  ✗ Unexpected error: {e}")
                    total_failed += 1
        else:
            logger.info("No finished audiobooks found that need deletion")

    # Summary
    logger.info("=" * 50)
    summary_parts = [f"{total_deleted} deleted", f"{total_failed} failed"]
    if min_age is not None:
        summary_parts.append(f"{total_skipped_age} skipped (too recent)")
    logger.info(f"Cleanup complete: {', '.join(summary_parts)}")
    if dry_run:
        logger.info("(DRY RUN - no actual deletions were performed)")


if __name__ == '__main__':
    main()
