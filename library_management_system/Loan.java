public class Loan{

    private Item item;
    private User user;

    public Loan(Item _item_, User _user_){
        
        item = _item_;
        user = _user_;
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

    public boolean isBorrowedBy(User user) {
        return this.user.getId() == user.getId();
    }

    public void close() {
        item.returnItem();
    }

    public String toString(){
        return item + " is borrowed by " + user;
    }
}