###
# Base Python main template for MCV architecture
# Author: Michael Cornelison
# Created: 2025-08-06
# Updates:
# - Initial creation
# - Added OBD2Controller for handling OBD-II communication
###

import json
from controller.base_controller import Controller
from model import base_model
from view import base_view
from controller.obd2_controller import OBD2Controller

def main():
    # Load config
    with open("config.json", "r") as f:
        config = json.load(f)
    bt_address = config.get("bt_address")
    # Initialize Model, View, OBD2 Controller
    model = base_model.Model()
    view = base_view.View()
    controller = OBD2Controller(bt_address, model, view)
    # Start the application
    controller.run()

if __name__ == "__main__":
    main()
