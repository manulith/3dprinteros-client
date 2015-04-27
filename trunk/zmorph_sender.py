import smoothie_sender

class Sender(smoothie_sender.Sender):
    def __init__(self, profile, usb_info, app):
        smoothie_sender.Sender.__init__(self, profile, usb_info, app)


