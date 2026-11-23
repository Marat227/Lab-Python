"""CSV writer with explicit physical units and timestamps."""
from __future__ import annotations
import csv
from datetime import datetime, timezone
from pathlib import Path

class CsvRecorder:
    def __init__(self, filename):
        self.path = Path(filename)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open('w', newline='', encoding='utf-8')
        self.writer = csv.writer(self.file)
        self.writer.writerow(['time_s','ch1_v','ch2_v'])

    def write(self, t, x, y):
        self.writer.writerows((f'{a:.9f}', f'{b:.9f}', f'{c:.9f}') for a,b,c in zip(t,x,y))
        self.file.flush()

    def close(self):
        self.file.close()
