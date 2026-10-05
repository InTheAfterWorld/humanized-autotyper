public class Reservation{

    private Item item;
    private User user;

    public Reservation(Item _item_, User _user_){
        
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
        return item + " is reserved by " + user;
    }
}