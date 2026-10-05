public class Magazine extends Item {
    private int issueNumber;

    public Magazine(int id, String title, String author, String genre,
                    double rating, int issueNumber) {
        super(id, title, author, genre, rating);
        this.issueNumber = issueNumber;
    }

    public int getIssueNumber() {
        return issueNumber;
    }

    public String getType() {
        return "Magazine";
    }
}