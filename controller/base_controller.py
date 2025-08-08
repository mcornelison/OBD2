class Controller:
    def __init__(self, model, view):
        self.model = model
        self.view = view

    def run(self):
        self.model.set_data("Hello, MCV!")
        data = self.model.get_data()
        self.view.display(data)
