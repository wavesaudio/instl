import instlInstanceBase

class InstlInstance(instlInstanceBase.InstlInstanceBase):
    def __init__(self):
        super(InstlInstance, self).__init__()
        self.var_replacement_pattern = "%\g<var_name>%"

