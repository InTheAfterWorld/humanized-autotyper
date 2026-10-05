public class Reservation{

    private Item item;
    private User user;
    private boolean cancelled;

    public Reservation(Item item, User user){
        this.item = item;
        this.user = user;
        cancelled = false;
    }

    public Item getItem() {
        return item;
    }

    public User getUser() {
        return user;
    }

    public boolean isFor(Item item) {
        return this.item.getId() == item.getId();
    }

    public boolean isMadeBy(User user) {
        return this.user.getId() == user.getId();
    }

    public void cancel() {
        cancelled = true;
    }

    public boolean isCancelled() {
        return cancelled;
    }

    public String toString(){
        return item + " is reserved by " + user;
    }
}