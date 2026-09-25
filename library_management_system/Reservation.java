public class Reservation{

    private Item item;
    private User user;

    public Reservation(Item _item_, User _user_){
        
        item = _item_;
        user = _user_;
    }

    public String toString(){
        return user + ": " + item;
    }
}