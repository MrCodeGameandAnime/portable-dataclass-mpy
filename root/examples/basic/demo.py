from models import Reading


def main():
    first = Reading(21)
    other = Reading(value=21)
    first.notes.append("bench")
    print(first.value, first.unit, first.notes)
    print(other.notes)


if __name__ == "__main__":
    main()
