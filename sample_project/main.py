from utils import greet
from helpers.math_tools import add


def main():
    """
    Main entry point of the program.
    Greets the user and displays the result of a simple addition.
    """
    name = "Julien"
    print(greet(name))
    print("2 + 3 =", add(2, 3))


if __name__ == "__main__":
    main()
