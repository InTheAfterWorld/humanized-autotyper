public class Employee extends User{

    public Employee(int id, String name){
        super(id, name);
    }

    public void createRequest(Item item, String type) {
        if (item == null) {
            System.out.println("Item not found.");
            return;
        }

        if (library != null) {
            library.addRequest(new EmployeeRequest(this, item, type));
        }

        System.out.println(getName() + " requested " + item.getTitle() + " (" + type + ").");
    }

    public void returnEmployeeItem(Item item) {
        if (item == null) {
            System.out.println("Item not found.");
            return;
        }

        item.setAvailable(true);

        System.out.println(getName() + " returned " + item.getTitle() + ".");
    }
}