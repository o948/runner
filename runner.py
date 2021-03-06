#!/usr/bin/env python3

import fnmatch
import heapq
import os
import shutil
import subprocess
import sys
import termios
import threading
import time
import tty

from datetime import datetime


ISO_8601 = '%Y-%m-%dT%H:%M:%S.%f'


class LogParseError(Exception):
    pass


class Runner:
    def __init__(self, cmd_path, jobs_dir, pattern, log_path):
        self._cmd = cmd_path
        self._jobs_dir = jobs_dir
        self._pattern = pattern
        self._log = open(log_path, 'a')

        self._jobs = set()
        self._done = {}
        self._started = {}

        self._lock = threading.Lock()
        self._waiting = threading.Condition(self._lock)

        self._nworkers = 0
        self._mtime = 0


    def start(self):
        threading.Thread(target=self._update_loop, daemon=True).start()

        old = termios.tcgetattr(sys.stdin)
        try:
            tty.setcbreak(sys.stdin)
            self._control_loop()
        except KeyboardInterrupt:
            pass
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSAFLUSH, old)


    def load_log(self, path=None):
        if path is None:
            path = self._log.name
        with open(path) as f:
            started = {}
            done = {}
            for i, line in enumerate(f):
                try:
                    ts, event, job = line.rstrip().split(' ')
                    ts = datetime.strptime(ts, ISO_8601).timestamp()
                except:
                    raise LogParseError('{}: invalid line {}'.format(f.name, i+1))
                if event == 'started':
                    started[job] = ts
                elif event == 'done':
                    done[job] = ts - started.pop(job)
        with self._lock:
            self._done = done


    def _log_write(self, ts, event, job):
        ts = ts.strftime(ISO_8601)
        print('{} {} {}'.format(ts, event, job), file=self._log, flush=True)


    def _control_loop(self):
        running = 0
        while True:
            c = sys.stdin.read(1)
            if c == '+':
                self._nworkers += 1
                if running < self._nworkers:
                    threading.Thread(target=self._worker, daemon=True).start()
                    running += 1
                else:
                    with self._lock:
                        self._notify_some_waiting()
            elif c == '-' and self._nworkers:
                self._nworkers -= 1


    def _update_loop(self):
        last_status = None
        while True:
            self._update_jobs()
            status = self._status_line()
            if status != last_status:
                print('\x1b[1;32m{:%H:%M:%S}\t{}\x1b[0m'.format(datetime.now(), status))
                last_status = status
            time.sleep(1)


    def _worker(self):
        while True:
            job = self._job_get()
            argv = [self._cmd, os.path.join(self._jobs_dir, job)]
            returncode = subprocess.call(argv, stdout=sys.stdout, stderr=sys.stdout)
            if returncode == 0:
                self._job_done(job)
            else:
                self._job_retry(job)


    def _job_get(self):
        with self._lock:
            while not self._can_start():
                self._waiting.wait()
            job = self._jobs.pop()
            ts = datetime.now()
            self._started[job] = ts.timestamp()
            self._log_write(ts, 'started', job)
            return job


    def _job_done(self, job):
        ts = datetime.now()
        with self._lock:
            self._log_write(ts, 'done', job)
            self._done[job] = ts.timestamp() - self._started.pop(job)
            self._notify_some_waiting()


    def _job_retry(self, job):
        ts = datetime.now()
        with self._lock:
            self._log_write(ts, 'failed', job)
            self._started.pop(job)
            self._jobs.add(job)
            self._notify_some_waiting()


    def _update_jobs(self):
        mtime = os.stat(self._jobs_dir).st_mtime
        if self._mtime == mtime:
            return
        self._mtime = mtime

        files = []
        for fname in os.listdir(self._jobs_dir):
            if not fname.startswith('.') and fnmatch.fnmatch(fname, self._pattern):
                files.append(fname)

        with self._lock:
            jobs = set()
            for job in files:
                if job not in self._done and job not in self._started:
                    jobs.add(job)
            self._jobs = jobs
            self._notify_some_waiting()


    def _status_line(self):
        with self._lock:
            njobs = len(self._jobs)
            ndone = len(self._done)
            avg_time = sum(self._done.values()) / ndone if ndone else None
            started = list(self._started.values())
        nworkers = self._nworkers
        eta = self._eta(nworkers, njobs, started, avg_time)
        return self._fmt_status(len(started), nworkers, njobs + len(started), ndone, eta)


    def _fmt_status(self, nrunning, nworkers, njobs, ndone, eta):
        return '\t'.join([
            'running {}/{}'.format(nrunning, nworkers),
            'jobs {}/{}'.format(njobs, ndone),
            'eta {}'.format(eta)
        ])


    def _eta(self, nworkers, njobs, started, avg_time):
        if not avg_time:
            return '?'
        if not njobs:
            if not started:
                return '0'
            return self._fmt_eta(max(started) + avg_time)
        if not nworkers:
            return '\u221e'

        finish = list(map(lambda t: t + avg_time, started))
        heapq.heapify(finish)

        while len(finish) > nworkers:
            heapq.heappop(finish)
        while len(finish) < nworkers:
            heapq.heappush(finish, datetime.now().timestamp())

        while njobs:
            if njobs >= nworkers and max(finish) - finish[0] < avg_time:
                k = njobs // nworkers
                finish = list(map(lambda t: t + k*avg_time, finish))
                njobs %= nworkers
            else:
                heapq.heapreplace(finish, finish[0] + avg_time)
                njobs -= 1

        return self._fmt_eta(max(finish))


    def _fmt_eta(self, eta):
        sec = int(eta - datetime.now().timestamp())
        if sec <= 0:
            return '0'
        s = '{}s'.format(sec % 60)
        if 60 <= sec:
            s = '{}m '.format(sec // 60 % 60) + s
        if 60*60 <= sec:
            s = '{}h '.format(sec // 60 // 60) + s
        return s


    def _can_start(self):
        return max(0, min(len(self._jobs), self._nworkers - len(self._started)))


    def _notify_some_waiting(self):
        self._waiting.notify(self._can_start())


USAGE = 'usage: {} <command> <jobs-dir> [file-pattern]'


def main():
    if len(sys.argv) == 4:
        cmd, jobs_dir, pattern = sys.argv[1:]
    elif len(sys.argv) == 3:
        cmd, jobs_dir = sys.argv[1:]
        pattern = '*'
    else:
        print(USAGE.format(sys.argv[0]), file=sys.stderr)
        sys.exit(1)

    cmd_path = shutil.which(cmd)
    if not cmd_path:
        print('{}: {} command not found'.format(sys.argv[0], cmd), file=sys.stderr)
        sys.exit(1)

    log_path = os.path.join(jobs_dir, '.' + os.path.basename(cmd_path) + '.log')

    runner = Runner(cmd_path, jobs_dir, pattern, log_path)

    try:
        runner.load_log()
    except FileNotFoundError:
        pass
    except LogParseError as e:
        print('{}: {}'.format(sys.argv[0], e), file=sys.stderr)
        sys.exit(1)

    runner.start()


if __name__ == '__main__':
    main()

