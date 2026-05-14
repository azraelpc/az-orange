# AZ's "Orange TV Libre" EPG (v0.2b)

A lightweight web application built with Flask to visualize the Electronic Program Guide (EPG) for Orange TV Libre from Spain. 
Orange TV ibre: https://orangetv.orange.es/brw/Home_Inicio?bci=hm

It features a dark mode optimized design and a smart tracking system for your most-watched channels.

Demo site: https://orange.azraelpc.com/

## Features

- Live Mode: Shows what is currently broadcasting across all available channels.
- Date Navigation: Allows browsing the programming schedule for the last 8 days.
- Frequent Channels: An automatic section highlighting the 6 most visited channels based on local click statistics.
- Real-time Filter: Integrated search bar to filter by channel name or program title.
- Direct Links: Deep links to watch content (Live or "Last 7 Days" catch-up) directly on the official Orange TV website.
- Modern Interface: Developed with Tailwind CSS, fully responsive and optimized for mobile devices.

## Requirements

- Python 3.10 or higher.
- Required libraries: Flask, requests, pandas, urllib3.

## Installation

1. Install the required dependencies via pip:

   pip install flask requests pandas urllib3

## Usage

1. Run the main script:

   python app.py

2. Access the application through your browser at: http://localhost:5000

## Technical Details

- SSL Adapter: The code implements the `OrangeSSLAdapter` class to configure the security level to `SECLEVEL=1`, a technical requirement for compatibility with Orange TV's API endpoints.
- Statistics Persistence: Channel click tracking is stored in `stats_clics.json` using a thread-safe locking mechanism (Lock) and atomic writing (via temporary files) to prevent data corruption.
- Cache Management: Global structures are used to cache channel name mapping and EPG data for days already queried, optimizing load speeds and reducing network traffic.

## Security and Deployment Notes

- Gitignore: It is recommended to add `stats_clics.json`, `stats_clics.json.tmp`, and `__pycache__` folders to your repository's `.gitignore` file.

## Disclaimer

This project is for personal and educational purposes only. It has no affiliation with Orange Spain. The user is responsible for complying with the terms and conditions of the original content platform.
