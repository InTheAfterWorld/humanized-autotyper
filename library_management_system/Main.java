import java.util.Scanner;

public class Main {
    static Scanner input = new Scanner(System.in);
    static Library library = new Library();

    public static void main(String[] args) {
        library.loadInventory("inventory.txt");

        MasterLibrarian master = new MasterLibrarian(1, "Master Librarian");
        Employee employee = new Employee(2, "John Employee");
        User user = new User(3, "Alice Student");

        library.addUser(master);
        library.addUser(employee);
        library.addUser(user);

        int choice;

        do {
            System.out.println("\n===== LIBRARY =====");
            System.out.println("1. Search");
            System.out.println("2. Borrow");
            System.out.println("3. Return");
            System.out.println("4. Reserve");
            System.out.println("5. Employee Request");
            System.out.println("6. Approve Request");
            System.out.println("7. Reject Request");
            System.out.println("8. Add Item");
            System.out.println("9. Return Employee Item");
            System.out.println("10. Dispose Item");
            System.out.println("11. Inventory");
            System.out.println("12. Loans");
            System.out.println("13. Reservations");
            System.out.println("14. Employee Requests");
            System.out.println("0. Exit");
            System.out.print("Choice: ");

            choice = input.nextInt();
            input.nextLine();

            if (choice == 1) {
                search();
            } else if (choice == 2) {
                borrow();
            } else if (choice == 3) {
                returnItem();
            } else if (choice == 4) {
                reserve();
            } else if (choice == 5) {
                employeeRequest();
            } else if (choice == 6) {
                approveRequest(master);
            } else if (choice == 7) {
                rejectRequest(master);
            } else if (choice == 8) {
                addItem(master);
            } else if (choice == 9) {
                returnEmployeeItem();
            } else if (choice == 10) {
                disposeItem(master);
            } else if (choice == 11) {
                library.showInventory();
            } else if (choice == 12) {
                library.showLoans();
            } else if (choice == 13) {
                library.showReservations();
            } else if (choice == 14) {
                library.showRequests();
            }

        } while (choice != 0);

        System.out.println("Goodbye.");
    }

    public static void search() {
        System.out.print("Search: ");
        String text = input.nextLine();

        library.search(text);
    }

    public static void borrow() {
        System.out.print("Item ID: ");
        int itemId = input.nextInt();

        System.out.print("User ID: ");
        int userId = input.nextInt();

        User user = library.findUser(userId);

        if (user == null) {
            System.out.println("User not found.");
            return;
        }

        user.borrow(library.findItem(itemId));
    }

    public static void returnItem() {
        System.out.print("Item ID: ");
        int itemId = input.nextInt();

        System.out.print("User ID: ");
        int userId = input.nextInt();

        User user = library.findUser(userId);

        if (user == null) {
            System.out.println("User not found.");
            return;
        }

        user.returnItem(library.findItem(itemId));
    }

    public static void reserve() {
        System.out.print("Item ID: ");
        int itemId = input.nextInt();

        System.out.print("User ID: ");
        int userId = input.nextInt();

        User user = library.findUser(userId);

        if (user == null) {
            System.out.println("User not found.");
            return;
        }

        user.reserve(library.findItem(itemId));
    }

    public static void employeeRequest() {
        System.out.print("Employee ID: ");
        int employeeId = input.nextInt();

        System.out.print("Item ID: ");
        int itemId = input.nextInt();
        input.nextLine();

        System.out.print("Request type: ");
        String type = input.nextLine();

        User user = library.findUser(employeeId);

        if (!(user instanceof Employee)) {
            System.out.println("Invalid employee.");
            return;
        }

        Employee employee = (Employee) user;

        employee.createRequest(library.findItem(itemId), type);
    }

    public static void approveRequest(MasterLibrarian master) {
        library.showRequests();

        System.out.print("Request number: ");
        int index = input.nextInt();

        master.approveRequest(library.getRequest(index));
    }

    public static void rejectRequest(MasterLibrarian master) {
        library.showRequests();

        System.out.print("Request number: ");
        int index = input.nextInt();

        master.rejectRequest(library.getRequest(index));
    }

    public static void addItem(MasterLibrarian master) {
        System.out.print("ID: ");
        int id = input.nextInt();
        input.nextLine();

        System.out.print("Title: ");
        String title = input.nextLine();

        System.out.print("Author: ");
        String author = input.nextLine();

        System.out.print("Genre: ");
        String genre = input.nextLine();

        System.out.print("Rating: ");
        double rating = input.nextDouble();

        System.out.println("1. Book");
        System.out.println("2. Magazine");
        System.out.println("3. Movie");
        System.out.println("4. AudioBook");
        System.out.print("Type: ");
        int type = input.nextInt();

        System.out.print("Pages / Issue / Duration: ");
        int extra = input.nextInt();

        Item item;

        if (type == 1) {
            item = new Book(id, title, author, genre, rating, extra);
        } else if (type == 2) {
            item = new Magazine(id, title, author, genre, rating, extra);
        } else if (type == 3) {
            item = new Movie(id, title, author, genre, rating, extra);
        } else {
            item = new AudioBook(id, title, author, genre, rating, extra);
        }

        master.addItem(item);
    }

    public static void returnEmployeeItem() {
        System.out.print("Item ID: ");
        int itemId = input.nextInt();

        System.out.print("Employee ID: ");
        int employeeId = input.nextInt();

        User user = library.findUser(employeeId);

        if (!(user instanceof Employee)) {
            System.out.println("Invalid employee.");
            return;
        }

        Employee employee = (Employee) user;

        employee.returnEmployeeItem(library.findItem(itemId));
    }

    public static void disposeItem(MasterLibrarian master) {
        System.out.print("Item ID: ");
        int itemId = input.nextInt();

        master.disposeItem(library.findItem(itemId));
    }
}