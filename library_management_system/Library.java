import java.util.ArrayList;
import java.io.File;
import java.io.FileNotFoundException;
import java.util.Scanner;

public class Library {
    private ArrayList<Item> items;
    private ArrayList<User> users;
    private ArrayList<Loan> loans;
    private ArrayList<Reservation> reservations;
    private ArrayList<EmployeeRequest> requests;

    public Library(){
        items = new ArrayList<>();
        users = new ArrayList<>();
        loans = new ArrayList<>();
        reservations = new ArrayList<>();
        requests = new ArrayList<>();
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

    public void search(String text) {
        String query = text.toLowerCase();

        boolean found = false;

        for (Item item : items) {
            if (item.getTitle().toLowerCase().contains(query)
                    || item.getAuthor().toLowerCase().contains(query)
                    || item.getGenre().toLowerCase().contains(query)
                    || item.getType().toLowerCase().contains(query)
                    || String.valueOf(item.getRating()).contains(query)) {
                System.out.println(item);
                found = true;
            }
        }

        if (!found) {
            System.out.println("No items matched \"" + text + "\".");
        }
    }

    public void addUser(User user){
        users.add(user);
        user.setLibrary(this);
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

    public void addLoan(Loan loan) {
        loans.add(loan);
    }

    public void addReservation(Reservation reservation) {
        reservations.add(reservation);
    }

    public void addRequest(EmployeeRequest request) {
        requests.add(request);
    }

    void removeLoan(Item item) {
        for (int i = 0; i < loans.size(); i++) {
            if (loans.get(i).isFor(item)) {
                loans.get(i).close();
                loans.remove(i);
                break;
            }
        }
    }

    Reservation findReservation(Item item) {
        for (Reservation reservation : reservations) {
            if (reservation.isFor(item) && !reservation.isCancelled()) {
                return reservation;
            }
        }

        return null;
    }

    Reservation findReservationByUser(Item item, User user) {
        for (Reservation reservation : reservations) {
            if (reservation.isFor(item) && reservation.isMadeBy(user) && !reservation.isCancelled()) {
                return reservation;
            }
        }

        return null;
    }

    EmployeeRequest getRequest(int index) {
        if (index < 0 || index >= requests.size()) {
            return null;
        }

        return requests.get(index);
    }

    void addNewItem(Item item) {
        items.add(item);
    }

    void removeItem(Item item) {
        items.remove(item);

        for (int i = 0; i < reservations.size(); i++) {
            if (reservations.get(i).isFor(item)) {
                reservations.get(i).cancel();
                reservations.remove(i);
                break;
            }
        }

        for (int i = 0; i < loans.size(); i++) {
            if (loans.get(i).isFor(item)) {
                loans.get(i).close();
                loans.remove(i);
                break;
            }
        }
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