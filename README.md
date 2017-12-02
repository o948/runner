# runner
Tool to execute specified command on a set of files in parallel.

## Usage
```
$ runner command file-pattern
```
will execute `command` with each of the files matching `file-pattern` on a number of processes.

Number of processes can be incremented and decremented using `+` and `-` keyboard keys.

When the `runner` is running it shows:
- number of processes currently working and number of processes set
- number of files left to process and total number of files processed
- estimated time to wait

E.g.:
```
12:10:48   running 19/19   jobs 3583/35700   eta 5h 52m 47s
```

## Requirements
Python 3
