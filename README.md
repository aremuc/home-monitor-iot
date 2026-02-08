# Home Monitor IoT System

This project simulates a home monitoring system using a Raspberry Pi client and a FastAPI backend.

Since this is a school project, no real home monitoring camera was used. Instead, the Raspberry Pi simulator uploads random images from a folder to represent camera captures.

The server receives the images, sends them to the Imagga image tagging API, and stores the results in a SQLite database.

## Features
- Image upload API
- AI image tagging using Imagga
- SQLite database storage
- Tag search by date range
- Person detection endpoint
- Popular tags endpoint
- Raspberry Pi image upload simulator

## Tech Stack
Python, FastAPI, SQLite, Requests, Imagga API

## Run Server
uvicorn server:app --reload

## Run Pi Simulator
python pi.py