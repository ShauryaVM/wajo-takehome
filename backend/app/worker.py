import time


def main():
    # Real sync loop lands once providers exist. Keep the process alive for compose.
    while True:
        time.sleep(30)


if __name__ == "__main__":
    main()
