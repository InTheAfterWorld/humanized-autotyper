public class EmployeeRequest {
    private Employee employee;
    private Item item;
    private String type;
    private boolean approved;

    public EmployeeRequest(Employee employee, Item item, String type) {
        this.employee = employee;
        this.item = item;
        this.type = type;
        approved = false;
    }

    public Employee getEmployee() {
        return employee;
    }

    public Item getItem() {
        return item;
    }

    public String getType() {
        return type;
    }

    public boolean isApproved() {
        return approved;
    }

    public void approve() {
        approved = true;
    }

    public String toString() {
        return employee.getName() + " | "
                + item.getTitle() + " | "
                + type + " | "
                + (approved ? "Approved" : "Pending");
    }
}