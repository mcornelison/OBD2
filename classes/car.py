class Car:
    def __init__(self, vin=None, make=None, model=None, year=None, color=None):
        self.vin = vin
        self.make = make
        self.model = model
        self.year = year
        self.color = color

    def __str__(self):
        return f"Car(VIN={self.vin}, Make={self.make}, Model={self.model}, Year={self.year}, Color={self.color})"

    def to_dict(self):
        return {
            "vin": self.vin,
            "make": self.make,
            "model": self.model,
            "year": self.year,
            "color": self.color
        }
