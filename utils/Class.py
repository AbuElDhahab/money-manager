class account:
    def __init__(self, id, name, percentage, balance):
        self.id = id
        self.name = name
        self.percentage = float(percentage) / 100
        self.balance = float(balance)

    def add(self, income):
        try:
            self.balance += float(income) * self.percentage
            return self.balance
        except:
            raise Exception("Something went wrong with updating balance account")
        
    def subtract(self, expenses):
        try:
            self.balance -= float(expenses)
            return self.balance
        except:
            raise Exception("Somthing went wrong with updating balance account")