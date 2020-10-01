
#include <simtbx/nanoBragg/nanoBragg.h>
#include <vector>
#include <boost/ptr_container/ptr_vector.hpp>

namespace simtbx {
namespace nanoBragg {

class derivative_manager{
  public:
    derivative_manager();
    void initialize(int sdim, int fdim);
    af::flex_double raw_pixels;
    double value; // the value of the parameter
    double dI; // the incremental derivative
    bool refine_me;
    void increment_image(int idx, double value);
};


class rot_manager: public derivative_manager{
  public:
    rot_manager();
    virtual ~rot_manager(){}
    virtual void set_R();
    void increment(
        double fudge,
        mat3 X, mat3 Y, mat3 Z,
        mat3 N, mat3 U, mat3 B,
        vec3 q, vec3 V,
        double Hrad, double Fcell, double Flatt,
        double source_I, double capture_fraction, double omega_pixel);
    //void increment(
    //    int Na, int Nb, int Nc,
    //    double hfrac, double kfrac, double lfrac,
    //    double fudge,
    //    mat3 U, mat3 A, mat3 B, mat3 C,
    //    vec3 a, vec3 b, vec3 c,  vec3 q,
    //    double Hrad, double Fcell, double Flatt,
    //    double source_I, double capture_fraction, double omega_pixel);

    mat3 XYZ;
    mat3 R, dR;
}; // end of rot_manager

class ucell_manager: public derivative_manager{
  public:
    ucell_manager();
    virtual ~ucell_manager(){}
    void increment(
        vec3 V, mat3 NABC, mat3 UR, vec3 q, mat3 Ot,
        double Hrad, double Fcell, double Flatt, double fudge,
        double source_I, double capture_fraction, double omega_pixel);

    mat3 dB;
    //void set_dB(){
    //}
};

class rotX_manager: public rot_manager{
  public:
    rotX_manager();
    void set_R();
};
class rotY_manager: public rot_manager{
  public:
    rotY_manager();
    void set_R();
};
class rotZ_manager: public rot_manager{
  public:
    rotZ_manager();
    void set_R();
};

class diffBragg: public nanoBragg{
  public:
  diffBragg(const dxtbx::model::Detector& detector, const dxtbx::model::Beam& beam,
            int verbose, int panel_id);

  ~diffBragg(){};
  void initialize_managers();
  void vectorize_umats();
  void add_diffBragg_spots();
  void init_raw_pixels_roi();
  void zero_raw_pixel_rois();
  void set_ucell_derivative_matrix(int refine_id, af::shared<double> const& value);
  //void reset_derivative_pixels(int refine_id);

  /* methods for interacting with the derivative managers */
  void refine(int refine_id);
  void set_value( int refine_id, double value);
  double get_value( int refine_id);
  af::flex_double get_derivative_pixels(int refine_id);
  af::flex_double get_raw_pixels_roi();

  mat3 Umatrix;
  mat3 Bmatrix;
  mat3 Omatrix;
  mat3 Bmat_realspace, NABC;
  mat3 RXYZ;
  std::vector<mat3> RotMats;
  std::vector<mat3> dRotMats;
  std::vector<mat3> R3;

  vec3 a_vec, ap_vec;
  vec3 b_vec, bp_vec;
  vec3 c_vec, cp_vec;
  vec3 q_vec; // scattering vector

  std::vector<mat3> UMATS;
  std::vector<mat3> UMATS_RXYZ;
  //bool vectorized_umats;

  /* derivative managers */
  std::vector<boost::shared_ptr<rot_manager> > rot_managers;
  std::vector<boost::shared_ptr<ucell_manager> > ucell_managers;

  double* floatimage_roi;
  af::flex_double raw_pixels_roi;

}; // end of diffBragg

} // end of namespace nanoBragg
} // end of namespace simtbx
