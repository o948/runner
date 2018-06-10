# runner
Tool to execute specified command on a set of files in parallel.

## Usage
```
runner command jobs-dir [file-pattern]
```
is like
```bash
for job in jobs-dir/file-pattern; do
  command "$job"
done
```
but
- multiple jobs are processed in parallel (use `+` and `-` keyboard keys to set number of processes)
- failed jobs are retried
- the set of jobs is periodically refreshed
- `runner` can be safely restarted (state saved in `jobs-dir/.command.log`)

When the `runner` is running it shows:
- number of processes currently working and number of processes set
- number of jobs left to process and total number of jobs processed already
- estimated time to wait

E.g.:
```
12:10:48   running 19/19   jobs 3583/35700   eta 5h 52m 47s
```

## Requirements
Python 3
