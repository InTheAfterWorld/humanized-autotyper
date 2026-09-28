public class User{
    
    private int id;
    private String name;

    public User(int _id_, String _name_){
        id = _id_;
        name = _name_;
    }

    public int getId() {
        return id;
    }

    public String getName() {
        return name;
    }
}