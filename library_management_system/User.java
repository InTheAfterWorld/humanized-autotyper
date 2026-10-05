public class User{

    private int id;
    private String name;
    protected Library library;

    public User(int id, String name){
        this.id = id;
        this.name = name;
    }

    public int getId() {
        return id;
    }

    public String getName() {
        return name;
    }

    public void setLibrary(Library library) {
        this.library = library;
    }

    public void borrow(Item item) {
        if (item == null) {
            System.out.println("Item not found.");
            return;
        }

        if (!item.isAvailable()) {
            System.out.println("Item is unavailable.");
            return;
        }

        item.borrow();

        if (library != null) {
            library.addLoan(new Loan(item, this));
        }

        System.out.println(name + " borrowed " + item.getTitle() + ".");
    }

    public void returnItem(Item item) {
        if (item == null) {
            System.out.println("Item not found.");
            return;
        }

        if (library != null) {
            library.removeLoan(item);
        } else {
            item.returnItem();
        }

        System.out.println(name + " returned " + item.getTitle() + ".");

        if (library != null) {
            Reservation reservation = library.findReservation(item);

            if (reservation != null) {
                System.out.println("This item is reserved for " + reservation.getUser().getName() + ".");
            }
        }
    }

    public void reserve(Item item) {
        if (item == null) {
            System.out.println("Item not found.");
            return;
        }

        if (item.isAvailable()) {
            System.out.println("Item is available to borrow.");
            return;
        }

        if (library != null) {
            if (library.findReservationByUser(item, this) != null) {
                System.out.println("You have already reserved this item.");
                return;
            }

            if (library.findReservation(item) != null) {
                System.out.println("Item is already reserved.");
                return;
            }

            library.addReservation(new Reservation(item, this));
        }

        System.out.println(name + " reserved " + item.getTitle() + ".");
    }

    public String toString() {
        return name + " (ID " + id + ")";
    }
}