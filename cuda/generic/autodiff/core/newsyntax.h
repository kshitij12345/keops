#ifndef NEWSYNTAX
#define NEWSYNTAX

#define Vx(N,DIM) _X<N,DIM>()

#define Vy(N,DIM) _Y<N,DIM>()

#define Pm(N) _P<N>()

#define Factorize(F,G) Factorize<decltype(F),decltype(G)>()

#define Grad(F,V,GRADIN)  Grad<decltype(F),decltype(V),decltype(GRADIN)>()

#define IntCst(N) IntConstant<N>
#define Cst(p) Constant<decltype(p)>()

template < class FA, class FB >
Add<FA,FB> operator+(FA fa, FB fb)
{
	return Add<FA,FB>();
}

template < class FA, class FB >
Scal<FA,FB> operator*(FA fa, FB fb)
{
	return Scal<FA,FB>();
}

#define Exp(f) Exp<decltype(f)>()

#define Pow(f,M) Pow<decltype(f),M>()

#define Square(f) Square<decltype(f)>()

template < class F >
Minus<F> operator-(F f)
{
	return Minus<F>();
}

template < class FA, class FB >
Subtract<FA,FB> operator-(FA fa, FB fb)
{
	return Subtract<FA,FB>();
}

#define Inv(f) Inv<decltype(f)>()

#define IntInv(f) IntInv<decltype(f)>()

template < class FA, class FB >
Divide<FA,FB> operator/(FA fa, FB fb)
{
	return Divide<FA,FB>();
}

#define Log(f) Log<decltype(f)>()

#define Powf(fa,fb) Powf<decltype(fa),decltype(fb)>()

#define Sqrt(f) Sqrt<decltype(f)>()

template < class FA, class FB >
Scalprod<FA,FB> operator,(FA fa, FB fb)
{
	return Scalprod<FA,FB>();
}

#define SqNorm2(f) SqNorm2<decltype(f)>()

#define SqDist(f,g) SqDist<decltype(f),decltype(g)>()



#define GaussKernel(OOS2,X,Y,Beta) GaussKernel<decltype(OOS2),decltype(X),decltype(Y),decltype(Beta)>()

#define GaussKernel_(DIMPOINT,DIMVECT) GaussKernel_<DIMPOINT,DIMVECT>()
#define LaplaceKernel(DIMPOINT,DIMVECT) LaplaceKernel<DIMPOINT,DIMVECT>()
#define EnergyKernel(DIMPOINT,DIMVECT) EnergyKernel<DIMPOINT,DIMVECT>()

#endif // NEWSYNTAX