public class EmployeeRequest {
    private Employee employee;
    private Item item;
    private String type;
    private boolean approved;
    private boolean rejected;

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

    public boolean isPending() {
        return !approved && !rejected;
    }

    public void approve() {
        approved = true;
    }

    public void reject() {
        rejected = true;
    }

    public String toString() {
        String status;

        if (approved) {
            status = "Approved";
        } else if (rejected) {
            status = "Rejected";
        } else {
            status = "Pending";
        }

        return employee.getName() + " | "
                + item.getTitle() + " | "
                + type + " | "
                + status;
    }
}