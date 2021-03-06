from __future__ import print_function

import os
import time
import subprocess

from colorama import Fore, Style
from watchdog.events import (
    FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent,
    FileMovedEvent, FileDeletedEvent)
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from .spooler import EventSpooler


EVENT_NAMES = {
    FileModifiedEvent: 'modified',
    FileCreatedEvent: 'created',
    FileMovedEvent: 'moved',
    FileDeletedEvent: 'deleted',
}
WATCHED_EVENTS = list(EVENT_NAMES)
DEFAULT_EXTENSIONS = ['.py']
CLEAR_COMMAND = 'cls' if os.name == 'nt' else 'clear'
BEEP_CHARACTER = '\a'
STYLE_NORMAL = Fore.RESET
STYLE_HIGHLIGHT = Fore.CYAN + Style.NORMAL + Style.BRIGHT


class ChangeHandler(FileSystemEventHandler):
    """Listens for changes to files and re-runs tests after each change."""
    def __init__(self, auto_clear=False, beep_on_failure=True,
                 onpass=None, onfail=None, beforerun=None, extensions=[],
                 args=None, spool=True, verbose=False, quiet=False):
        super(ChangeHandler, self).__init__()
        self.auto_clear = auto_clear
        self.beep_on_failure = beep_on_failure
        self.onpass = onpass
        self.onfail = onfail
        self.beforerun = beforerun
        self.extensions = extensions or DEFAULT_EXTENSIONS
        self.args = args or []
        self.spooler = None
        if spool:
            self.spooler = EventSpooler(0.2, self.on_queued_events)
        self.verbose = verbose
        self.quiet = quiet

    def on_queued_events(self, events):
        summary = []
        for event in events:
            paths = [event.src_path]
            if isinstance(event, FileMovedEvent):
                paths.append(event.dest_path)
            event_name = EVENT_NAMES[type(event)]
            paths = tuple(map(os.path.relpath, paths))
            if any(os.path.splitext(path)[1].lower() in self.extensions
                   for path in paths):
                summary.append((event_name, paths))
        if summary:
            self.run(sorted(set(summary)))

    def on_any_event(self, event):
        if isinstance(event, tuple(WATCHED_EVENTS)):
            if self.spooler is not None:
                self.spooler.enqueue(event)
            else:
                self.on_queued_events([event])

    def run(self, summary=None):
        """Called when a file is changed to re-run the tests with py.test."""
        if self.auto_clear:
            subprocess.call(CLEAR_COMMAND, shell=True)
        command = ' '.join(['py.test'] + self.args)
        if summary and not self.auto_clear:
            print()
        if not self.quiet:
            highlight = lambda arg: STYLE_HIGHLIGHT + arg + STYLE_NORMAL
            msg = 'Running: {}'.format(highlight(command))
            if summary:
                if self.verbose:
                    file_lines = ['    {:9s}'.format(event_name + ':') + ' ' +
                                  ' -> '.join(map(highlight, paths))
                                  for event_name, paths in summary]
                    msg = ('Changes detected in files:\n{}\n\nRerunning: {}'
                           .format('\n'.join(file_lines), highlight(command)))
                else:
                    msg = ('Changes detected, rerunning: {}'
                           .format(highlight(command)))
            print(STYLE_NORMAL + msg + Fore.RESET + Style.NORMAL)
        if self.beforerun:
            os.system(self.beforerun)
        exit_code = subprocess.call(['py.test'] + self.args,
                                    shell=subprocess.mswindows)
        passed = exit_code == 0

        # Beep if failed
        if not passed and self.beep_on_failure:
            print(BEEP_CHARACTER, end='')

        # Run custom commands
        if passed and self.onpass:
            os.system(self.onpass)
        elif not passed and self.onfail:
            os.system(self.onfail)


def watch(directories=[], ignore=[], auto_clear=False, beep_on_failure=True,
          onpass=None, onfail=None, beforerun=None, poll=False, extensions=[],
          args=[], spool=True, verbose=False, quiet=False):
    if not directories:
        directories = ['.']
    directories = [os.path.abspath(directory) for directory in directories]
    for directory in directories:
        if not os.path.isdir(directory):
            raise ValueError('Directory not found: ' + directory)

    if ignore:
        recursive_dirs, non_recursive_dirs = split_recursive(
            directories, ignore)
    else:
        recursive_dirs = directories
        non_recursive_dirs = []

    # Initial run
    event_handler = ChangeHandler(auto_clear, beep_on_failure,
                                  onpass, onfail, beforerun, extensions, args,
                                  spool, verbose, quiet)
    event_handler.run()

    # Setup watchdog
    observer = PollingObserver() if poll else Observer()
    for directory in recursive_dirs:
        observer.schedule(event_handler, path=directory, recursive=True)
    for directory in non_recursive_dirs:
        observer.schedule(event_handler, path=directory, recursive=False)

    # Watch and run tests until interrupted by user
    try:
        observer.start()
        while True:
            time.sleep(1)
        observer.join()
    except KeyboardInterrupt:
        observer.stop()


def samepath(left, right):
    return (os.path.abspath(os.path.normcase(left)) ==
            os.path.abspath(os.path.normcase(right)))


def split_recursive(directories, ignore):
    non_recursive_dirs = []
    recursive_dirs = []
    for directory in directories:
        subdirs = [os.path.join(directory, d)
                   for d in os.listdir(directory)
                   if os.path.isdir(d)]
        filtered = [subdir for subdir in subdirs
                    if not any(samepath(os.path.join(directory, d), subdir)
                               for d in ignore)]
        if len(subdirs) == len(filtered):
            recursive_dirs.append(directory)
        else:
            non_recursive_dirs.append(directory)
            recursive_dirs.extend(filtered)

    return sorted(set(recursive_dirs)), sorted(set(non_recursive_dirs))
