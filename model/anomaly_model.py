class AnomalyModel:
    def __init__(self):
        self.anomalies = []

    def add_anomaly(self, anomaly):
        self.anomalies.append(anomaly)

    def get_anomalies(self):
        return self.anomalies
