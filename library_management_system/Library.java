import java.util.*;
import java.io.*;

public class Library {
    private ArrayList<Item> items;
    private ArrayList<User> users;
    private ArrayList<Loan> loans;
    private ArrayList<Reservation> reservations;
    private ArrayList<EmployeeRequest> employeeRequests;

    public Library(){
        items = new ArrayList<>();
        users = new ArrayList<>();
        loans = new ArrayList<>();
        reservations = new ArrayList<>();
        employeeRequests = new ArrayList<>();
    }

    public void loadInventory(String fileName) {
        try {
            Scanner file = new Scanner(new File(fileName));

            while (file.hasNextLine()) {
                String[] data = file.nextLine().split("\\|");

                String type = data[0];
                int id = Integer.parseInt(data[1]);
                String title = data[2];
                String author = data[3];
                String genre = data[4];
                double rating = Double.parseDouble(data[5]);
                int extra = Integer.parseInt(data[6]);

                if (type.equals("BOOK")) {
                    items.add(new Book(id, title, author, genre, rating, extra));
                } else if (type.equals("MAGAZINE")) {
                    items.add(new Magazine(id, title, author, genre, rating, extra));
                } else if (type.equals("MOVIE")) {
                    items.add(new Movie(id, title, author, genre, rating, extra));
                } else if (type.equals("AUDIOBOOK")) {
                    items.add(new AudioBook(id, title, author, genre, rating, extra));
                }
            }

            file.close();

        } catch (FileNotFoundException e) {
            System.out.println("Inventory file not found.");
        }
    }

    public void addUser(User user){
        users.add(user);
    }

    public Item findItem(int id){
        for (Item item: items){
            if (item.getId() == id) {
                return item;
            }
        }

        return null;
    }

    public User findUser(int id){
        for (User user: users){
            if (user.getId() == id) {
                return user;
            }
        }

        return null;
    }

    public void borrow(int itemId, int userId) {
        Item item = findItem(itemId);
        User user = findUser(userId);

        if (item == null || user == null) {
            System.out.println("Item or user not found.");
            return;
        }

        if (!item.isAvailable()) {
            System.out.println("Item is unavailable.");
            return;
        }

        item.setAvailable(false);
        loans.add(new Loan(item, user));

        System.out.println("Item borrowed.");
    }

        public void returnItem(int itemId) {
        Item item = findItem(itemId);

        if (item == null) {
            System.out.println("Item not found.");
            return;
        }

        for (int i = 0; i < loans.size(); i++) {
            if (loans.get(i).getItem().getId() == itemId) {
                loans.remove(i);
                break;
            }
        }

        item.setAvailable(true);

        System.out.println("Item returned.");

        if (hasReservation(item)) {
            System.out.println("This item is reserved for a user.");
        }
    }

    public void addItem(Item item, MasterLibrarian ml){
        items.add(item);
    }

    public void returnItem(int itemId) {
        Item item = findItem(itemId);

        if (item == null) {
            System.out.println("Item not found.");
            return;
        }

        for (int i = 0; i < loans.size(); i++) {
            if (loans.get(i).getItem().getId() == itemId) {
                loans.remove(i);
                break;
            }
        }

        item.setAvailable(true);

        System.out.println("Item returned.");

        if (hasReservation(item)) {
            System.out.println("This item is reserved.");
        }
    }

    public void reserve(int itemId, int userId) {
        Item item = findItem(itemId);
        User user = findUser(userId);

        if (item == null || user == null) {
            System.out.println("Item or user not found.");
            return;
        }

        if (item.isAvailable()) {
            System.out.println("Item is available to borrow");
            return;
        }

        reservations.add(new Reservation(item, user));

        System.out.println("Item reserved.");
    }


    private boolean hasReservation(Item item) {
        for (Reservation reservation : reservations) {
            if (reservation.getItem().getId() == item.getId()) {
                return true;
            }
        }

        return false;
    }

    public void createRequest(int employeeId, int itemId, String type) {
        User user = findUser(employeeId);
        Item item = findItem(itemId);

        if (!(user instanceof Employee) || item == null) {
            System.out.println("Invalid employee or item.");
            return;
        }

        Employee employee = (Employee) user;

        requests.add(new EmployeeRequest(employee, item, type));

        System.out.println("Request created.");
    }

    public void approveRequest(int index, MasterLibrarian librarian) {
        if (index < 0 || index >= requests.size()) {
            System.out.println("Invalid request.");
            return;
        }

        EmployeeRequest request = requests.get(index);

        if (request.isApproved()) {
            System.out.println("Request already approved.");
            return;
        }

        if (!request.getItem().isAvailable()) {
            System.out.println("Item is unavailable.");
            return;
        }

        request.approve();
        request.getItem().setAvailable(false);

        System.out.println("Request approved.");
    }

    public void addNewItem(Item item, MasterLibrarian librarian) {
        if (findItem(item.getId()) != null) {
            System.out.println("That ID already exists.");
            return;
        }

        items.add(item);

        System.out.println("Item added.");
    }

    public void returnEmployeeItem(int itemId) {
        Item item = findItem(itemId);

        if (item == null) {
            System.out.println("Item not found.");
            return;
        }

        item.setAvailable(true);
        System.out.println("Employee item returned.");
    }

    public void disposeItem(int itemId) {
        Item item = findItem(itemId);

        if (item == null) {
            System.out.println("Item not found.");
            return;
        }

        items.remove(item);

        System.out.println("Item disposed.");
    }

    public void showInventory() {
        System.out.println("\n--- INVENTORY ---");

        for (Item item : items) {
            System.out.println(item);
        }
    }

    public void showLoans() {
        System.out.println("\n--- LOANS ---");

        if (loans.isEmpty()) {
            System.out.println("No current loans.");
            return;
        }

        for (Loan loan : loans) {
            System.out.println(loan);
        }
    }

    public void showReservations() {
        System.out.println("\n--- RESERVATIONS ---");

        if (reservations.isEmpty()) {
            System.out.println("No reservations.");
            return;
        }

        for (Reservation reservation : reservations) {
            System.out.println(reservation);
        }
    }

    public void showRequests() {
        System.out.println("\n--- EMPLOYEE REQUESTS ---");

        if (requests.isEmpty()) {
            System.out.println("No employee requests.");
            return;
        }

        for (int i = 0; i < requests.size(); i++) {
            System.out.println(i + ": " + requests.get(i));
        }
    }
}