import csv, json, os

def log_snapshot(snapshot):
    with open('data/price_snapshots.csv', 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=snapshot.keys())
        if f.tell() == 0:
            writer.writeheader()
        writer.writerow(snapshot)

def log_window(window):
    with open('data/opportunity_windows.csv', 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=window.keys())
        if f.tell() == 0:
            writer.writeheader()
        writer.writerow(window)

def log_error(error):
    with open('data/errors.log', 'a') as f:
        f.write(json.dumps(error) + '\n')
