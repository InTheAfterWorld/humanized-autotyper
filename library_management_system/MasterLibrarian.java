public class MasterLibrarian extends Employee {

    public MasterLibrarian(int id, String name) {
        super(id, name);
    }

    public void approveRequest(EmployeeRequest request) {
        if (request == null) {
            System.out.println("Request not found.");
            return;
        }

        if (!request.isPending()) {
            System.out.println("Request is not pending.");
            return;
        }

        if (!request.getItem().isAvailable()) {
            System.out.println("Item is unavailable.");
            return;
        }

        request.approve();
        request.getItem().borrow();

        System.out.println(getName() + " approved the request for " + request.getItem().getTitle() + ".");
    }

    public void rejectRequest(EmployeeRequest request) {
        if (request == null) {
            System.out.println("Request not found.");
            return;
        }

        if (!request.isPending()) {
            System.out.println("Request is not pending.");
            return;
        }

        request.reject();

        System.out.println(getName() + " rejected the request for " + request.getItem().getTitle() + ".");
    }

    public void addItem(Item item) {
        if (item == null) {
            System.out.println("Item not found.");
            return;
        }

        if (library == null) {
            return;
        }

        if (library.findItem(item.getId()) != null) {
            System.out.println("That ID already exists.");
            return;
        }

        library.addNewItem(item);

        System.out.println(getName() + " added " + item.getTitle() + ".");
    }

    public void disposeItem(Item item) {
        if (item == null) {
            System.out.println("Item not found.");
            return;
        }

        if (library == null) {
            return;
        }

        if (library.findItem(item.getId()) == null) {
            System.out.println("Item not in the inventory.");
            return;
        }

        library.removeItem(item);

        System.out.println(getName() + " disposed " + item.getTitle() + ".");
    }
}