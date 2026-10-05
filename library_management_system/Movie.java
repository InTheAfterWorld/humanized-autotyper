public class Movie extends Item {
    private int duration;

    public Movie(int id, String title, String author, String genre,
                 double rating, int duration) {
        super(id, title, author, genre, rating);
        this.duration = duration;
    }

    public int getDuration() {
        return duration;
    }

    public String getType() {
        return "Movie";
    }
}