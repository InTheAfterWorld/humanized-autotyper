public class Customer extends User{

    public Customer(int id, String name) {
        super(id, name);
    }

    public boolean borrowItem(){
        return false;
    }

    public boolean returnItem(){
        return false;
    }
}