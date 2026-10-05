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

    public String toString(){
        return item + " is borrowed by " + user;
    }
}