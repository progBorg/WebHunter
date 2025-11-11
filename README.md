# WebHunter
Scrape websites and push new results to the user.

## Features

### Sources
- [x] Funda scraper
- [ ] AutoScout24

### Communication methods
- [x] Pushover

### To Do
- [x] Create basics
- [ ] Endurance test
- [ ] Make more sources

## Prerequisites
This package has been built for Python v3.10 on Linux.
If you use a different Python version, this software may not work as expected.

## Installation

### Installing WebHunter
- Clone this repository to your device, e.g., `git clone https://github.com/progBorg/webhunter.git ~/webhunter`
- Navigate to the repository root directory, e.g., `cd ~/webhunter`
- Copy the file `webhunter.yaml.example` to `webhunter.yaml` and change whatever configuration you like
- Copy the file `install/webhunter.service` to `/etc/systemd/system/`
- Install links for system-wide use:
    - `sudo ln -s $PWD/webhunter/webhunter.py /usr/local/bin/webhunter.py`
    - `sudo ln -s $PWD/webhunter.yaml /etc/webhunter.yaml`
- Enable the WebHunter service with `sudo systemctl enable webhunter`. It now starts at system startup.

## Running
Once installed, the service may be started immediately using `sudo service webhunter start`.
You may stop the service using `sudo service webhunter stop`.

(c) Tom Veldman 2024 - 2025\
Software licensed under the MIT license
