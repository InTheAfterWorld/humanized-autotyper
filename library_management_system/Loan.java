public class Loan{

    private Item item;
    private User user;

    public Loan(Item _item_, User _user_){
        
        item = _item_;
        user = _user_;
    }

    public String toString(){
        return user + ": " + item;
    }
}