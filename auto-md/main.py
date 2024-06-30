import tkinter as tk
from gui import AutoMDApp

def main():
    root = tk.Tk()
    app = AutoMDApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()