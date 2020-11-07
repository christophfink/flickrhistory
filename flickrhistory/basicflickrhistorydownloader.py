#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#   Copyright (C) 2020 Christoph Fink, University of Helsinki
#
#   This program is free software; you can redistribute it and/or
#   modify it under the terms of the GNU General Public License
#   as published by the Free Software Foundation; either version 3
#   of the License, or (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program; if not, see <http://www.gnu.org/licenses/>.


"""Download (all) georeferenced flickr posts."""


__all__ = ["BasicFlickrHistoryDownloader"]


import collections
import datetime
import queue
import math
import multiprocessing
import sys
import threading
import time

from .apikeymanager import ApiKeyManager
from .cache import Cache
from .cacheupdaterthread import CacheUpdaterThread
from .config import Config
from .photodownloaderthread import PhotoDownloaderThread
from .sigtermreceivedexception import SigTermReceivedException
from .timespan import TimeSpan
from .userprofileupdaterthread import UserProfileUpdaterThread


class BasicFlickrHistoryDownloader:
    """Download (all) georeferenced flickr posts."""

    NUM_WORKERS = multiprocessing.cpu_count() + 1  # 1 == user_profile_updater

    NUM_MANAGERS = 2  # main thread + cache_updater

    def __init__(self):
        """Intialise a FlickrHistory object."""
        self._todo_deque = collections.deque()
        self._done_queue = queue.Queue()

        self._worker_threads = []

        with Config() as config:
            self._api_key_manager = ApiKeyManager(config["flickr_api_keys"])

    def download(self):
        """Download all georeferenced flickr posts."""
        for gap in self.gaps_in_download_history:
            self._todo_deque.append(gap)

        try:
            # start downloaders
            for _ in range(self.NUM_WORKERS - 1):
                worker = PhotoDownloaderThread(
                    self._api_key_manager,
                    self._todo_deque,
                    self._done_queue
                )
                worker.start()
                self._worker_threads.append(worker)

            # start user profile updater
            self.user_profile_updater_thread = UserProfileUpdaterThread(
                self._api_key_manager
            )
            self.user_profile_updater_thread.start()

            # start cache updater
            self.cache_updater_thread = CacheUpdaterThread(self._done_queue)
            self.cache_updater_thread.start()

            while threading.active_count() > self.NUM_MANAGERS:
                self.report_progress()
                time.sleep(0.1)

        except (
            KeyboardInterrupt,
            SigTermReceivedException
        ):
            self.announce_shutdown()
            for worker in self._worker_threads:
                worker.shutdown.set()
            self.user_profile_updater_thread.shutdown.set()

        finally:
            self.summarise_overall_progress()
            for worker in self._worker_threads:
                worker.join()
            self.user_profile_updater_thread.shutdown.set()
            self.user_profile_updater_thread.join()
            self.cache_updater_thread.shutdown.set()
            self.cache_updater_thread.join()

    def report_progress(self):
        """Report current progress."""
        print(
            (
                "Downloaded metadata for {photos: 6d} photos "
                + "and {profiles: 4d} user profiles "
                + "using {workers:d} workers, "
                + "{todo:d} time slots to cover"
            ).format(
                photos=sum([worker.count for worker in self._worker_threads]),
                profiles=self.user_profile_updater_thread.count,
                workers=(threading.active_count() - self.NUM_MANAGERS),
                todo=len(self._todo_deque)
            ),
            file=sys.stderr,
            end="\r"
        )

    def announce_shutdown(self):
        """Tell the user that we initiated shutdown."""
        print(
            "Cleaning up" + (" " * 69),  # 80 - len("Cleaning up")
            file=sys.stderr,
            end="\r"
        )

    def summarise_overall_progress(self):
        """
        Summarise what we have done.

        (Called right before exit)
        """
        print(
            (
                "Downloaded {photos:d} photos "
                + "and {profiles:d} user profiles"
            ).format(
                photos=sum([worker.count for worker in self._worker_threads]),
                profiles=self.user_profile_updater_thread.count
            ),
            file=sys.stderr
        )

    @property
    def gaps_in_download_history(self):
        """Find gaps in download history."""
        already_downloaded = self.already_downloaded_timespans
        one_day = datetime.timedelta(days=1)  # for comparison

        for i in range(len(already_downloaded) - 1):
            gap = TimeSpan(
                already_downloaded[i].end,
                already_downloaded[i + 1].start
            )
            if gap.duration > one_day:
                divider = math.ceil(gap.duration / one_day)
                for part_of_gap in gap / divider:
                    yield part_of_gap
            else:
                yield gap

    @property
    def already_downloaded_timespans(self):
        """Figure out for which time spans we already have data."""
        with Cache() as cache:
            try:
                timespans = cache["already downloaded"]
            except KeyError:
                timespans = []

        # delete existing 0-length time spans
        timespans = [
            timespan for timespan in timespans
            if timespan.duration > datetime.timedelta(0)
        ]

        # add 0-length time spans for
        # - “beginning of all time”
        #  - now()
        #
        # beginning of time cannot be simply epoch 0, because the flickr API
        # matches dates slightly fuzzily, i.e. we would get ALL (or many) photos
        # that have a corrupted or missing upload date (don’t ask me, how flickr
        # managed to mess up the upload date)
        # on top of that, some small timestamps seems to be simply 0 +- timezone offset
        # which invalidates pretty much the entire first day after epoch 0
        # this is why we use epoch 0 + 1 day
        zero = (
            datetime.datetime.fromtimestamp(0, tz=datetime.timezone.utc)
            + datetime.timedelta(days=1)
        )
        now = datetime.datetime.now(datetime.timezone.utc)
        timespans += [
            TimeSpan(zero, zero),
            TimeSpan(now, now)
        ]

        return sum(timespans)  # sum resolves overlaps
