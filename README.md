# Webhunter
Scrape websites and push new results to the user.

## Features

### Sources
- [x] Funda scraper

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

### Installing Huizenjacht
- Clone this repository to your device, e.g., `git clone https://github.com/progBorg/webhunter.git ~/webhunter`
- Navigate to the repository root directory, e.g., `cd ~/webhunter`
- Copy the file `huizenjacht.yaml.example` to `huizenjacht.yaml` and change whatever configuration you like
- Copy the file `install/huizenjacht.service` to `/etc/systemd/system/`
- Install links for system-wide use:
    - `sudo ln -s $PWD/huizenjacht/huizenjacht.py /usr/local/bin/huizenjacht.py`
    - `sudo ln -s $PWD/huizenjacht.yaml /etc/huizenjacht.yaml`
- Enable the huizenjacht service with `sudo systemctl enable huizenjacht`. It now starts at system startup.

## Running
Once installed, the service may be started immediately using `sudo service huizenjacht start`.
You may stop the service using `sudo service huizenjacht stop`.

(c) Tom Veldman 2024\
Software licensed under the MIT license
